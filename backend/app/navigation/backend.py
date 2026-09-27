"""Optional, asynchronous hardware-world bridge; camera/BLE never await HTTP."""
import asyncio
from datetime import datetime, timezone
import logging
import time

import httpx


class BackendBridge:
    def __init__(self, url, traffic):
        self.url, self.traffic = url, traffic
        self.world = None
        self.updated = 0
        self.sample = []
        self.events = []
        self.arrivals = []
        self.error = 'Waiting for backend'

    def current(self, now):
        return self.world if now-self.updated < .75 else None

    def target(self, location, world):
        p = world['map']['locations'][location]
        x1,y1,x2,y2 = self.traffic.arena
        return (x1+p['x']/world['map']['width']*(x2-x1),
                y1+p['y']/world['map']['height']*(y2-y1))

    def capture(self, robots, traffic):
        x1,y1,x2,y2 = self.traffic.arena
        self.sample = [dict(robot_id=r.profile.robot_id,
            online=bool(r.ble and r.ble.connected), blocked=traffic.blocked,
            pose=({'x': (r.pose.center_x-x1)/(x2-x1),
                   'y': (r.pose.center_y-y1)/(y2-y1),
                   'heading': (r.pose.heading+r.config.heading_offset_degrees)%360}
                  if r.pose else None), captured=r.last_seen,
            timestamp=datetime.now(timezone.utc).isoformat()) for r in robots]
        self.events.extend(traffic.events)
        self.events = self.events[-10:]
        traffic.events.clear()

    async def run(self):
        async with httpx.AsyncClient(base_url=self.url, timeout=.5) as client:
            while True:
                try:
                    response = await client.get('/world')
                    response.raise_for_status()
                    world = response.json()
                    if world['mode'] != 'hardware':
                        raise ValueError('Backend must run with GAME_MODE=hardware')
                    old_session = self.world and self.world['session_id']
                    if old_session != world['session_id']:
                        self.events.clear()
                        self.arrivals.clear()
                    self.world, self.updated, self.error = world, time.monotonic(), None
                    session = world['session_id']
                    for sample in self.sample:
                        robot_id = sample['robot_id']
                        response = await client.post(f'/robots/{robot_id}/health', json={
                            'session_id': session, 'online': sample['online'], 'blocked': sample['blocked']})
                        response.raise_for_status()
                        pose = sample['pose']
                        if pose and sample['captured'] is not None and time.monotonic()-sample['captured'] < .5:
                            response = await client.post(f'/robots/{robot_id}/pose', json={
                                'session_id': session, 'timestamp': sample['timestamp'],
                                'pose': {**pose, 'x': pose['x']*world['map']['width'], 'y': pose['y']*world['map']['height']}})
                            response.raise_for_status()
                    if self.events:
                        event = self.events[0]
                        response = await client.post('/agent-chat/traffic', json={'session_id':session, **event})
                        response.raise_for_status()
                        self.events.pop(0)
                    if self.arrivals:
                        arrival = self.arrivals[0]
                        if arrival['session_id'] == session:
                            response = await client.post(f"/robots/{arrival['robot_id']}/arrived",
                                json={k:v for k,v in arrival.items() if k!='robot_id'})
                            if response.status_code != 409:
                                response.raise_for_status()
                        self.arrivals.pop(0)
                except (httpx.HTTPError, ValueError, KeyError) as error:
                    self.updated = 0
                    message = f'{type(error).__name__}: {error}'
                    if message != self.error:
                        logging.warning('Backend bridge stopped: %s', message)
                    self.error = message
                await asyncio.sleep(.1)


class TaskFollower:
    """Local, latched permission to follow authoritative tasks. A enables; any
    loss of authority/health or SPACE revokes permission until another A.
    """
    def __init__(self, bridge):
        self.bridge = bridge
        self.session = None
        self.keys = {}
        self.arrived = set()

    def stop(self, robots):
        self.session = None
        for robot in robots:
            robot.gate.stop()

    def update(self, robots, sample, now, world, *, arm=False):
        states = {r['id']: r for r in world['robots']} if world else {}
        healthy = bool(world and world['game']['status'] == 'RUNNING' and all(
            states[r.profile.robot_id]['physical']['online'] and
            states[r.profile.robot_id]['physical']['tracking'] == 'TRACKED' and
            not states[r.profile.robot_id]['physical']['blocked'] and
            not states[r.profile.robot_id]['physical']['stopped'] for r in robots))
        if not healthy or (self.session is not None and self.session != world['session_id']):
            self.stop(robots)
        if arm and healthy:
            self.session = world['session_id']
        if not world:
            return
        for robot in robots:
            state = states[robot.profile.robot_id]
            task = state['task']
            active = task and task['status'] in ('ASSIGNED', 'NAVIGATING')
            identity = (world['session_id'], task['id']) if active else None
            changed = self.keys.get(robot.profile.robot_id) != identity
            if changed:
                robot.gate.stop()
                robot.target = self.bridge.target(task['location'], world) if active else None
                self.keys[robot.profile.robot_id] = identity
                robot.observe(sample, now, 4)
            if (changed or arm) and identity and self.session == world['session_id']:
                robot.arm(now)
        # Keep idempotency memory bounded to current tasks.
        self.arrived.intersection_update(key for key in self.keys.values() if key)

    def report_arrivals(self, robots, world, traffic):
        if not world or self.session != world['session_id'] or traffic.blocked:
            return
        for robot in robots:
            identity = self.keys.get(robot.profile.robot_id)
            if identity and identity not in self.arrived and robot.pose and robot.geometry and robot.geometry.distance < robot.config.stop_distance:
                state = next(r for r in world['robots'] if r['id'] == robot.profile.robot_id)
                self.bridge.arrivals.append({'session_id': identity[0], 'task_id': identity[1],
                    'robot_id': robot.profile.robot_id, 'location': state['task']['location']})
                self.arrived.add(identity)
