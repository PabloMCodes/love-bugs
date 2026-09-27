"""Optional, asynchronous hardware-world bridge; camera/BLE never await HTTP."""
import asyncio
from datetime import datetime, timezone, timedelta
import logging
import math
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
        self.pending_stop = None
        self.observations = {}
        self.sent_observations = {}
        self.accepted_arrivals = set()

    def request_stop(self):
        """Latch operator intent until acknowledged; no HTTP in the control loop."""
        self.pending_stop = {'session_id': self.world['session_id'] if self.world else None}
        self.arrivals.clear()
        self.events.clear()
        self.updated = 0
        self.error = 'Local emergency stop: awaiting backend acknowledgement'

    async def deliver_stop(self, client):
        intent = self.pending_stop
        if intent is None:
            return
        if intent['session_id'] is None:
            response = await client.get('/world')
            response.raise_for_status()
            world = response.json()
            if world['mode'] != 'hardware':
                raise ValueError('Backend must run with GAME_MODE=hardware')
            intent['session_id'] = world['session_id']
        response = await client.post('/game/stop', json=intent)
        if response.status_code == 409 and response.json().get('error', {}).get('code') == 'SESSION_MISMATCH':
            logging.warning('Discarded emergency stop for an old backend session; local motion remains disarmed')
        else:
            response.raise_for_status()
            world = response.json()
            if (world['session_id'] != intent['session_id'] or
                    world['game']['status'] not in ('STOPPED', 'COMPLETED') or
                    any(not r['physical']['stopped'] or r['task'] is not None for r in world['robots'])):
                raise ValueError('Backend did not confirm stopped game and cancelled tasks')
            self.world = world
            logging.info('Backend acknowledged emergency stop; start game then press A to recover')
        if self.pending_stop is intent:
            self.pending_stop = None
        self.updated = 0  # Require another world poll before any new arm attempt.

    def current(self, now):
        return self.world if self.pending_stop is None and now-self.updated < .75 else None

    def target(self, location, world):
        p = world['map']['locations'][location]
        x1,y1,x2,y2 = self.traffic.arena
        return (x1+p['x']/world['map']['width']*(x2-x1),
                y1+p['y']/world['map']['height']*(y2-y1))

    def validate_map(self, world):
        expected = self.traffic.world_locations(world['map']['width'], world['map']['height'])
        actual = world['map']['locations']
        if set(actual) != set(expected) or any(
                not math.isclose(actual[name][axis], point[axis], abs_tol=1e-6)
                for name, point in expected.items() for axis in ('x', 'y')):
            raise ValueError('Destination map mismatch: restart hardware backend with '
                             'HARDWARE_TRAFFIC_CONFIG pointing to the same calibration')

    def capture(self, robots, traffic):
        x1,y1,x2,y2 = self.traffic.arena
        now = time.monotonic()
        for r in robots:
            previous = self.observations.get(r.profile.robot_id)
            if r.last_seen is not None and (previous is None or previous[0] != r.last_seen):
                self.observations[r.profile.robot_id] = (r.last_seen,
                    (datetime.now(timezone.utc)-timedelta(seconds=max(0,now-r.last_seen))).isoformat())
        self.sample = [dict(robot_id=r.profile.robot_id,
            online=bool(r.ble and r.ble.connected), blocked=traffic.blocked,
            pose=({'x': (r.pose.center_x-x1)/(x2-x1),
                   'y': (r.pose.center_y-y1)/(y2-y1),
                   'heading': (r.pose.heading+r.config.heading_offset_degrees)%360}
                  if r.pose else None), captured=r.last_seen,
            timestamp=self.observations.get(r.profile.robot_id, (None,None))[1]) for r in robots]
        self.events.extend(traffic.events)
        self.events = self.events[-10:]
        traffic.events.clear()

    async def run(self):
        async with httpx.AsyncClient(base_url=self.url, timeout=.5) as client:
            while True:
                try:
                    if self.pending_stop is not None:
                        await self.deliver_stop(client)
                        await asyncio.sleep(.1)
                        continue
                    response = await client.get('/world')
                    response.raise_for_status()
                    world = response.json()
                    if world['mode'] != 'hardware':
                        raise ValueError('Backend must run with GAME_MODE=hardware')
                    self.validate_map(world)
                    old_session = self.world and self.world['session_id']
                    if old_session != world['session_id']:
                        self.events.clear()
                        self.arrivals.clear()
                        self.sent_observations.clear()
                        self.accepted_arrivals.clear()
                    self.world, self.updated, self.error = world, time.monotonic(), None
                    session = world['session_id']
                    for sample in self.sample:
                        if self.pending_stop is not None:
                            break
                        robot_id = sample['robot_id']
                        response = await client.post(f'/robots/{robot_id}/health', json={
                            'session_id': session, 'online': sample['online'], 'blocked': sample['blocked']})
                        response.raise_for_status()
                        pose = sample['pose']
                        if (pose and sample['captured'] is not None and time.monotonic()-sample['captured'] < .5
                                and self.sent_observations.get(robot_id) != sample['captured']):
                            response = await client.post(f'/robots/{robot_id}/pose', json={
                                'session_id': session, 'timestamp': sample['timestamp'],
                                'pose': {**pose, 'x': pose['x']*world['map']['width'], 'y': pose['y']*world['map']['height']}})
                            response.raise_for_status()
                            self.sent_observations[robot_id] = sample['captured']
                    if self.pending_stop is not None:
                        continue
                    if self.events:
                        event = self.events[0]
                        response = await client.post('/agent-chat/traffic', json={'session_id':session, **event})
                        response.raise_for_status()
                        if self.events and self.events[0] is event:
                            self.events.pop(0)
                    if self.arrivals and self.pending_stop is None:
                        arrival = self.arrivals[0]
                        if self.arrival_is_current(arrival, world):
                            response = await client.post(f"/robots/{arrival['robot_id']}/arrived",
                                json={k:arrival[k] for k in ('session_id','task_id','location')})
                            if response.status_code != 409:
                                response.raise_for_status()
                                if response.json().get('accepted'):
                                    self.accepted_arrivals.add((session,arrival['task_id']))
                        if self.arrivals and self.arrivals[0] is arrival:
                            self.arrivals.pop(0)
                except (httpx.HTTPError, ValueError, KeyError) as error:
                    self.updated = 0
                    message = f'{type(error).__name__}: {error}'
                    if message != self.error:
                        logging.warning('Backend bridge stopped: %s', message)
                    self.error = message
                await asyncio.sleep(.1)

    def arrival_is_current(self, arrival, world):
        if (self.pending_stop is not None or arrival['session_id'] != world['session_id'] or
                world['game']['status'] != 'RUNNING'):
            return False
        state = next((r for r in world['robots'] if r['id'] == arrival['robot_id']),None)
        sample = next((s for s in self.sample if s['robot_id'] == arrival['robot_id']),None)
        task = state and state['task']
        if (not task or task['id'] != arrival['task_id'] or task['location'] != arrival['location'] or
                task['status'] not in ('ASSIGNED','NAVIGATING') or not sample or
                not sample['online'] or sample['blocked'] or not sample['pose'] or
                sample['captured'] is None or time.monotonic()-sample['captured'] >= .5 or
                state['physical']['stopped']):
            return False
        x1,y1,x2,y2 = self.traffic.arena
        pose = sample['pose']
        target = self.target(arrival['location'],world)
        return math.hypot(x1+pose['x']*(x2-x1)-target[0],
                          y1+pose['y']*(y2-y1)-target[1]) < arrival['tolerance_pixels']


class TaskFollower:
    """Local, latched permission to follow authoritative tasks. A enables; any
    loss of authority/health or SPACE revokes permission until another A.
    """
    def __init__(self, bridge):
        self.bridge = bridge
        self.session = None
        self.keys = {}
        self.arrived = set()
        self.settling = {}

    def stop(self, robots):
        self.session = None
        self.settling.clear()
        self.bridge.arrivals.clear()
        for robot in robots:
            robot.gate.stop()

    def update(self, robots, sample, now, world, *, arm=False):
        states = {r['id']: r for r in world['robots']} if world else {}
        healthy = bool(self.bridge.pending_stop is None and world and world['game']['status'] == 'RUNNING' and all(
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
                if active:
                    # Agent and local named selection share the target setter;
                    # only an enabled backend session may arm automatically.
                    robot.set_target(*self.bridge.target(task['location'], world))
                else:
                    robot.target = None
                self.keys[robot.profile.robot_id] = identity
                robot.observe(sample, now, 4)
            if (changed or arm) and identity and self.session == world['session_id']:
                robot.arm(now)
        # Keep idempotency memory bounded to current tasks.
        self.arrived.intersection_update(key for key in self.keys.values() if key)

    def report_arrivals(self, robots, world, traffic, *, now=None):
        now = time.monotonic() if now is None else now
        if not world or self.session != world['session_id'] or traffic.blocked:
            self.settling.clear()
            return
        current_keys = {key for key in self.keys.values() if key}
        self.bridge.accepted_arrivals.intersection_update(current_keys)
        for robot in robots:
            identity = self.keys.get(robot.profile.robot_id)
            queued = any((a['session_id'],a['task_id']) == identity for a in self.bridge.arrivals)
            if not queued and identity not in self.bridge.accepted_arrivals:
                self.arrived.discard(identity)
            settled = bool(identity and robot.pose and robot.geometry and
                robot.last_seen is not None and now-robot.last_seen < robot.config.marker_timeout and
                robot.geometry.distance < robot.config.stop_distance and robot.ble and
                robot.ble.connected and robot.ble.last_command == 'S')
            if not settled:
                self.settling.pop(robot.profile.robot_id,None)
                continue
            previous = self.settling.get(robot.profile.robot_id)
            if previous is None or previous[0] != identity:
                self.settling[robot.profile.robot_id] = (identity,robot.last_seen)
                continue
            if robot.last_seen-previous[1] < .3:
                continue
            if identity not in self.arrived and identity not in self.bridge.accepted_arrivals:
                state = next(r for r in world['robots'] if r['id'] == robot.profile.robot_id)
                self.bridge.arrivals.append({'session_id': identity[0], 'task_id': identity[1],
                    'robot_id': robot.profile.robot_id, 'location': state['task']['location'],
                    'tolerance_pixels':robot.config.stop_distance})
                self.arrived.add(identity)
