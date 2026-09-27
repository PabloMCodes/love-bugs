"""Conservative two-robot traffic: one moving reservation, checked grid detours.

All geometry is in camera pixels. Robots are circles covering their entire
turning sweep. Static obstacles and arena must be calibrated before enabling.
This does not sense contact or unseen obstacles.
"""
import heapq
import json
import logging
import math
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import uuid4

from app.navigation.controller import steer


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def segment_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = dx * dx + dy * dy
    t = max(0, min(1, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length)) if length else 0
    return distance(point, (start[0] + t * dx, start[1] + t * dy))


@dataclass
class TrafficConfig:
    calibrated: bool = False
    frame_width: int = 1280
    frame_height: int = 720
    arena: list = field(default_factory=lambda: [0, 0, 1280, 720])
    radii: dict = field(default_factory=lambda: {'robot-a': 55, 'robot-b': 55})
    margin: float = 30
    max_speed: float = 250
    stop_latency: float = 1.1
    grid: float = 25
    obstacles: list = field(default_factory=list)

    def __post_init__(self):
        if type(self.calibrated) is not bool:
            raise ValueError('calibrated must be a boolean')
        values = [self.frame_width, self.frame_height, self.margin, self.max_speed,
                  self.stop_latency, self.grid, *self.radii.values()]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError('Traffic dimensions, radii, margins and speed must be positive finite numbers')
        if set(self.radii) != {'robot-a', 'robot-b'}:
            raise ValueError('Traffic radii must specify robot-a and robot-b')
        for rect in [self.arena, *self.obstacles]:
            if len(rect) != 4 or any(not isinstance(v, (float, int)) or not math.isfinite(v) for v in rect):
                raise ValueError('Rectangles use [left, top, right, bottom] pixels')
            x1, y1, x2, y2 = rect
            if not (0 <= x1 < x2 <= self.frame_width and 0 <= y1 < y2 <= self.frame_height):
                raise ValueError('Traffic rectangles must be inside the calibrated frame')
        if self.frame_width * self.frame_height / self.grid ** 2 > 20000:
            raise ValueError('Traffic grid too fine; keep fewer than 20,000 cells')
        if self.stop_latency < 1:
            raise ValueError('stop_latency must cover tracking plus BLE stop latency (at least 1 second)')

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text()))


class TrafficController:
    def __init__(self, config):
        self.config = config
        self.owner = None
        self.last_owner = None
        self.route = []
        self.route_target = None
        self.reason = 'Traffic waiting for localization'
        self.events = []
        self.announced = None
        self.blocked = True
        self.release_at = 0
        self.last_stop = None

    def point(self, robot):
        return (robot.pose.center_x, robot.pose.center_y)

    def clearance(self, robot_id):
        return self.config.radii[robot_id] + self.config.margin

    def clear_segment(self, start, end, robot_id, peer):
        """Exact circle distance and slab test against expanded rectangles."""
        radius = self.clearance(robot_id)
        left, top, right, bottom = self.config.arena
        if any(not (left + radius < p[0] < right - radius and top + radius < p[1] < bottom - radius) for p in (start, end)):
            return False
        if segment_distance(peer[0], start, end) <= radius + self.config.radii[peer[1]]:
            return False
        for x1, y1, x2, y2 in self.config.obstacles:
            lo, hi = 0., 1.
            for a, b, lower, upper in ((start[0], end[0], x1-radius, x2+radius),
                                        (start[1], end[1], y1-radius, y2+radius)):
                delta = b-a
                if abs(delta) < 1e-9:
                    if not lower <= a <= upper:
                        lo, hi = 1., 0.
                        break
                else:
                    t1, t2 = sorted(((lower-a)/delta, (upper-a)/delta))
                    lo, hi = max(lo, t1), min(hi, t2)
            if lo <= hi:
                return False
        return True

    def plan(self, start, goal, robot_id, peer):
        if not self.clear_segment(start, start, robot_id, peer) or not self.clear_segment(goal, goal, robot_id, peer):
            return []
        if self.clear_segment(start, goal, robot_id, peer):
            return [goal]
        step = self.config.grid
        # A* over camera grid; segment checks include diagonal corner clearance.
        nearest = (round(start[0]/step), round(start[1]/step))
        seeds = [(nearest[0]+dx, nearest[1]+dy) for dx in (-1,0,1) for dy in (-1,0,1)]
        costs, parents, queue = {}, {}, []
        for node in seeds:
            p = (node[0]*step, node[1]*step)
            if self.clear_segment(start, p, robot_id, peer):
                costs[node] = distance(start, p)
                parents[node] = None
                heapq.heappush(queue, (costs[node]+distance(p, goal), costs[node], node))
        deadline = time.monotonic() + .04
        while queue:
            if time.monotonic() > deadline:
                return []  # Bound camera/BLE loop work; stopped retry via A.
            _, cost, node = heapq.heappop(queue)
            if cost != costs[node]:
                continue
            p = (node[0]*step, node[1]*step)
            if self.clear_segment(p, goal, robot_id, peer):
                path = [goal, p]
                while parents[node] is not None:
                    node = parents[node]
                    path.append((node[0]*step, node[1]*step))
                path.reverse()
                # Greedy visibility smoothing; every resulting segment checked.
                result, anchor = [], start
                while path:
                    index = max(i for i, q in enumerate(path) if self.clear_segment(anchor, q, robot_id, peer))
                    anchor = path[index]
                    result.append(anchor)
                    path = path[index+1:]
                return result
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nxt = (node[0]+dx, node[1]+dy)
                q = (nxt[0]*step, nxt[1]*step)
                new = cost + distance(p, q)
                if new < costs.get(nxt, math.inf) and self.clear_segment(p, q, robot_id, peer):
                    costs[nxt], parents[nxt] = new, node
                    heapq.heappush(queue, (new+distance(q,goal),new,nxt))
        return []

    def halt(self, robots, reason, *, disarm=True):
        if reason != self.last_stop:
            logging.warning('Traffic STOP: %s', reason)
        self.last_stop = reason
        self.reason, self.blocked = reason, True
        self.owner, self.route = None, []
        if disarm:
            for robot in robots:
                robot.gate.stop()
        return {r.profile.robot_id: 'S' for r in robots}

    def update(self, robots, now, shape, phase):
        cfg = self.config
        commands = {r.profile.robot_id: 'S' for r in robots}
        if not cfg.calibrated:
            return self.halt(robots, 'Calibrate traffic_config.json before movement')
        if shape != (cfg.frame_height, cfg.frame_width):
            return self.halt(robots, 'Camera resolution differs from traffic calibration')
        if any(r.pose is None for r in robots):
            return self.halt(robots, 'Both markers required; STOP both, then re-arm')
        separation = distance(*(self.point(r) for r in robots))
        if separation <= sum(cfg.radii.values()) + cfg.margin:
            return self.halt(robots, 'Too close: separate robots manually, then re-arm')
        for r in robots:
            peer = next(p for p in robots if p is not r)
            if not self.clear_segment(self.point(r), self.point(r), r.profile.robot_id,
                                      (self.point(peer), peer.profile.robot_id)):
                return self.halt(robots, 'Robot outside safe arena or inside obstacle margin')
        for r in robots:
            if r.geometry and r.geometry.distance < r.config.stop_distance:
                r.gate.stop()
        eligible = [r for r in robots if r.target_valid and r.geometry and r.geometry.distance >= r.config.stop_distance
                    and (phase == 3 or r.gate.armed)]
        if not eligible:
            self.reason, self.blocked = (('Stopped: ' + self.last_stop + '; press A after resolving')
                                         if self.last_stop else 'No armed movement pending'), False
            self.owner, self.route, self.announced = None, [], None
            for r in robots:
                if r.geometry and r.geometry.distance < r.config.stop_distance:
                    r.gate.stop()
            return commands
        self.last_stop = None
        owner = next((r for r in eligible if r.profile.robot_id == self.owner), None)
        if owner is None:
            candidates = sorted(eligible, key=lambda r: (r.profile.robot_id == self.last_owner, r.profile.robot_id))
            for r in candidates:
                peer = next(p for p in robots if p is not r)
                route = self.plan(self.point(r), r.target, r.profile.robot_id, (self.point(peer),peer.profile.robot_id))
                if route:
                    owner = r
                    self.owner = self.last_owner = r.profile.robot_id
                    self.release_at = now + cfg.stop_latency
                    self.route, self.route_target = route, r.target
                    break
            if owner is None:
                return self.halt(robots, 'No clear route: change target or reposition; both stopped')
        peer = next(r for r in robots if r is not owner)
        peer_info = (self.point(peer), peer.profile.robot_id)
        if self.route_target != owner.target or not self.route or not self.clear_segment(self.point(owner), self.route[0], self.owner, peer_info):
            self.route = self.plan(self.point(owner), owner.target, self.owner, peer_info)
            self.route_target = owner.target
        if not self.route:
            return self.halt(robots, 'Reserved route obstructed; both stopped')
        # Never turn intermediate arrival into MotionGate's final-arrival latch.
        while len(self.route) > 1 and distance(self.point(owner), self.route[0]) < 12:
            if not self.clear_segment(self.point(owner), self.route[1], self.owner, peer_info):
                break
            self.route.pop(0)
        waypoint = self.route[0]
        geometry = steer(owner.pose, waypoint, replace(owner.config, stop_distance=3 if len(self.route)>1 else owner.config.stop_distance))
        command = geometry.command
        if command == 'S' and len(self.route) > 1:
            return self.halt(robots, 'Waypoint corner lacks clearance; change target and re-arm')
        # Check actual current heading, not ideal route: cover blind travel through
        # tracking/BLE stop latency, including the full next movement pulse.
        if command == 'F':
            travel = cfg.max_speed * (cfg.stop_latency + owner.config.pulse_seconds)
            h = math.radians(geometry.heading)
            end = (owner.pose.center_x+travel*math.cos(h), owner.pose.center_y+travel*math.sin(h))
            if not self.clear_segment(self.point(owner), end, self.owner, peer_info):
                return self.halt(robots, 'Predicted movement lacks stopping clearance; both stopped')
        self.reason, self.blocked = f'{owner.profile.name} goes first; {peer.profile.name} waits', False
        signature = (self.owner, owner.target, peer.target)
        if signature != self.announced:
            self.events.append({'event_id': uuid4().hex, 'winner': self.owner,
                                'yielder': peer.profile.robot_id, 'detour': len(self.route)>1})
            self.events = self.events[-10:]
            self.announced = signature
        if now < self.release_at:
            self.reason += '; allowing previous movement to settle'
            return commands
        commands[self.owner] = (command if phase == 3 else owner.gate.command(
            command, now, owner.last_seen, True, owner.ble.connected))
        return commands
