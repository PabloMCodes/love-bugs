"""Two independently armed robots sharing one overhead camera. No avoidance."""

import asyncio
import logging
import time

import cv2

from app.navigation.__main__ import CameraWorker, draw
from app.navigation.controller import MotionGate, steer
from app.robots.client import BleController

WINDOW = 'Love Bugs navigation'
COLORS = ((255, 80, 255), (255, 220, 0))


class RobotControl:
    def __init__(self, profile, phase):
        self.profile = profile
        self.config = profile.config
        self.gate = MotionGate(self.config)
        self.ble = BleController(self.config) if phase == 4 else None
        self.target = None
        self.last_seen = None
        self.pose = None
        self.geometry = None
        self.target_valid = False
        self.desired = 'S'
        self.reason = 'Waiting for camera'

    def set_target(self, x, y):
        self.target = (x, y)
        self.gate.stop()
        logging.info('%s target=%s; press A to arm this robot', self.profile.name, self.target)

    def observe(self, sample, now, phase):
        self.pose = None
        self.target_valid = False
        self.reason = 'Waiting for camera'
        if sample:
            captured, frame, poses = sample
            pose = poses.get(self.profile.robot_id)
            if pose is not None:
                self.last_seen = captured
            age = now - captured
            self.reason = f'Stale camera frame ({age:.2f}s)' if age >= self.config.marker_timeout else 'Marker missing'
            if age < self.config.marker_timeout:
                self.pose = pose
            self.target_valid = (self.target is not None and
                                 0 <= self.target[0] < frame.shape[1] and
                                 0 <= self.target[1] < frame.shape[0])
        self.geometry = (steer(self.pose, self.target, self.config)
                         if self.pose and self.target_valid and phase >= 2 else None)
        self.desired = self.geometry.command if self.geometry and phase >= 3 else 'S'
        if self.pose:
            self.reason = 'Tracking' if self.target_valid else 'Click a target for this robot'

    def arm(self, now):
        fresh = self.pose is not None and self.target_valid and self.ble is not None and self.ble.connected
        self.gate.arm(now, fresh)
        logging.info('%s: %s', self.profile.name,
                     'ARMED' if fresh else f'ARM REJECTED: {self.reason}; check BLE connection')

    def command(self, now):
        return self.gate.command(self.desired, now, self.last_seen, self.pose is not None,
                                 self.ble.connected if self.ble else False)


async def stop_all(robots):
    for robot in robots:
        robot.gate.stop()
    results = await asyncio.gather(*(r.ble.send('S', force=True) for r in robots if r.ble),
                                   return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            logging.error('Stop delivery failed: %s', result)


async def run_fleet(args, profiles):
    robots = [RobotControl(profile, args.phase) for profile in profiles]
    selected = 0
    worker = CameraWorker(args.video if args.video else
                          (args.camera if args.camera is not None else profiles[0].config.camera_index),
                          profiles[0].config, robots=profiles)
    last_log = float('-inf')
    last_state = None
    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)

    def click(event, x, y, _flags, _data):
        if event == cv2.EVENT_LBUTTONDOWN and args.phase >= 2:
            robots[selected].set_target(x, y)

    cv2.setMouseCallback(WINDOW, click)
    try:
        # Connect sequentially as in the supplied working script. Neither moves.
        for robot in robots:
            if robot.ble:
                logging.info('Connecting to %s', robot.profile.name)
                await robot.ble.connect()
        worker.thread.start()
        while True:
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), ord('Q')) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key in (ord('w'), ord('W')):
                selected = 0
            elif key in (ord('e'), ord('E')):
                selected = 1
            if key == ord(' '):
                await stop_all(robots)
                logging.info('EMERGENCY STOP: both robots disarmed')
            if worker.error:
                raise RuntimeError(f'Camera failed: {worker.error}')
            if worker.done:
                logging.info('Video ended')
                break
            sample = worker.snapshot()
            now = time.monotonic()
            for robot in robots:
                robot.observe(sample, now, args.phase)
            if key in (ord('a'), ord('A')):
                robots[selected].arm(now)
            # One lost link stops the whole session; fresh tracking is per robot.
            if any(r.ble and not r.ble.connected for r in robots):
                raise RuntimeError('BLE disconnected; stopping both. Restart to reconnect and re-arm.')
            results = await asyncio.gather(*(r.ble.send(r.command(now)) for r in robots if r.ble),
                                           return_exceptions=True)
            errors = [result for result in results if isinstance(result, BaseException)]
            if errors:
                raise RuntimeError(f'BLE write failed; stopping both: {errors[0]}')
            lines = [f'Phase {args.phase} | selected robot: {robots[selected].profile.name}',
                     'W WALL-Y | E Eeva | click target | A arm selected | SPACE stop BOTH | Q quit']
            for robot in robots:
                ble_status = ('connected' if robot.ble.connected else 'disconnected') if robot.ble else 'off (dry run)'
                sent = robot.ble.last_command if robot.ble else 'NONE'
                lines.append(f'{robot.profile.name}: {"ARMED" if robot.gate.armed else "STOPPED"} '
                             f'BLE={ble_status} selected={robot.desired} sent={sent} | {robot.reason}')
                if robot.pose:
                    p = robot.pose
                    lines.append(f'  ID={p.marker_id} x={p.center_x:.1f} y={p.center_y:.1f} marker h={p.heading:.1f}')
                if robot.geometry:
                    g = robot.geometry
                    lines.append(f'  distance={g.distance:.1f}px heading={g.heading:.1f} '
                                 f'desired={g.desired_heading:.1f} error={g.error:+.1f}')
            state = tuple((r.gate.armed, r.desired) for r in robots)
            if now - last_log >= .5 or state != last_state:
                logging.info(' | '.join(lines))
                last_log, last_state = now, state
            if sample:
                frame = sample[1].copy()
                for index, robot in enumerate(robots):
                    target = robot.target if args.phase >= 2 else None
                    draw(frame, robot.pose if robot.geometry else None, target, robot.geometry, [], color=COLORS[index])
                    if target:
                        cv2.putText(frame, robot.profile.name, (int(target[0]) + 15, int(target[1])),
                                    cv2.FONT_HERSHEY_SIMPLEX, .6, COLORS[index], 2)
                draw(frame, None, None, None, lines)
                cv2.imshow(WINDOW, frame)
            await asyncio.sleep(.01)
    finally:
        for robot in robots:
            robot.gate.stop()
        # Attempt both stops concurrently before waiting for either disconnect.
        await asyncio.gather(*(r.ble.close() for r in robots if r.ble), return_exceptions=True)
        worker.stop_event.set()
        if worker.thread.is_alive():
            worker.thread.join(timeout=1)
        cv2.destroyAllWindows()
