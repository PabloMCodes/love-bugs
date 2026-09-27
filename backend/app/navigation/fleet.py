"""Two robots sharing a camera, with mandatory calibrated traffic control."""

import asyncio
import logging
import time

import cv2

from app.navigation.__main__ import CameraWorker, draw
from app.navigation.controller import MotionGate, steer
from app.robots.client import BleController
from app.navigation.traffic import DEFAULT_TRAFFIC_CONFIG, LOCATIONS, TrafficConfig, TrafficController
from app.navigation.backend import BackendBridge, TaskFollower
from app.navigation.calibrate import draw_destinations

WINDOW = 'Love Bugs navigation'
COLORS = ((255, 80, 255), (255, 220, 0))


class DestinationController:
    """Select saved targets on the running fleet; never create a second BLE client.

    Selection disarms the chosen robot. The UI or backend task follower retains
    responsibility for deliberate arming and all movement/safety checks.
    """
    def __init__(self, robots, traffic_config):
        self.robots = {robot.profile.robot_id: robot for robot in robots}
        self.config = traffic_config

    def go_to_location(self, robot_id, location):
        if robot_id not in self.robots:
            raise ValueError(f'Unknown robot: {robot_id}')
        self.robots[robot_id].gate.stop()
        if location not in LOCATIONS:
            raise ValueError(f'Unknown destination: {location}; choose {", ".join(LOCATIONS)}')
        if location not in self.config.service_points:
            raise ValueError(f'Configure the {location} service point in the calibration editor first')
        point = self.config.service_points[location]
        self.config.validate_point(point, location)
        self.robots[robot_id].set_target(*point)
        logging.info('%s destination=%s target=%s', robot_id, location, point)
        return tuple(point)


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


async def discover_fleet_devices(profiles, *, scanner=None):
    """Resolve every configured robot in one scan before opening either link."""
    if scanner is None:
        from bleak import BleakScanner
        scanner = BleakScanner
    logging.info('Scanning once for %s', ', '.join(profile.name for profile in profiles))
    discovered = await scanner.discover(timeout=10)
    resolved = {}
    for profile in profiles:
        wanted = profile.config.ble_device
        if profile.config.ble_direct_address:
            device = next((item for item in discovered if item.address == wanted), None)
        else:
            device = next((item for item in discovered if item.name == wanted), None)
        if device is None:
            visible = ', '.join(
                f'{item.name or "unnamed"} ({item.address})' for item in discovered
            ) or 'none'
            raise RuntimeError(
                f'BLE device {wanted!r} for {profile.name} was not found in the fleet scan. '
                f'Visible devices: {visible}'
            )
        resolved[profile.robot_id] = device
        logging.info('Resolved %s to %s', profile.name, device.address)
    return resolved


async def connect_fleet(robots, profiles):
    """Resolve the fleet together, then connect each robot without implicit scans."""
    devices = await discover_fleet_devices(profiles)
    for robot in robots:
        logging.info('Connecting to %s', robot.profile.name)
        await robot.ble.connect(device=devices[robot.profile.robot_id])


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
    traffic_path = (getattr(args, 'traffic_config', None) or DEFAULT_TRAFFIC_CONFIG).resolve()
    config = TrafficConfig.load(traffic_path)
    ignore_boundary = getattr(args, 'ignore_arena_boundary', False)
    traffic = TrafficController(config, ignore_arena_boundary=ignore_boundary)
    if ignore_boundary:
        logging.warning('Saved arena boundary DISABLED for this run; camera-frame, building and peer clearance remain active')
    destinations = DestinationController(robots, config)
    logging.info('Traffic configuration: %s | calibrated=%s | arena=%s | buildings=%d | frame=%sx%s',
                 traffic_path, config.calibrated, config.arena, len(config.obstacles),
                 config.frame_width, config.frame_height)
    if not config.calibrated:
        logging.warning('Traffic calibration is not reviewed: all motion will remain STOPPED')
    backend_url = getattr(args, 'backend_url', None)
    if backend_url:
        config.validate_destinations()
    bridge = BackendBridge(backend_url, traffic.config) if backend_url else None
    bridge_task = None
    follower = TaskFollower(bridge) if bridge else None
    worker = CameraWorker(args.video if args.video else
                          (args.camera if args.camera is not None else profiles[0].config.camera_index),
                          profiles[0].config, robots=profiles)
    last_log = float('-inf')
    last_state = None
    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)

    def click(event, x, y, _flags, _data):
        if event == cv2.EVENT_LBUTTONDOWN and args.phase >= 2 and not bridge:
            robots[selected].set_target(x, y)

    cv2.setMouseCallback(WINDOW, click)
    startup = None
    try:
        worker.thread.start()
        if bridge:
            bridge_task = asyncio.create_task(bridge.run())
        if args.phase == 4:
            # Keep OpenCV responsive and show camera frames while the one fleet
            # scan and sequential BLE connections run. Robots remain stopped.
            startup = asyncio.create_task(connect_fleet(robots, profiles))
            await asyncio.sleep(0)
            displayed = False
            while not startup.done():
                key = cv2.waitKey(1) & 0xFF
                if key in (ord('q'), ord('Q')) or (
                    displayed and cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1
                ):
                    logging.info('BLE startup cancelled by user')
                    startup.cancel()
                    await asyncio.gather(startup, return_exceptions=True)
                    return
                if worker.error:
                    raise RuntimeError(f'Camera failed during BLE startup: {worker.error}')
                if worker.done:
                    raise RuntimeError('Camera stopped during BLE startup')
                sample = worker.snapshot()
                if sample:
                    display = sample[1].copy()
                    lines = [
                        'Phase 4 | camera ready | connecting robots',
                        'Robots remain STOPPED | Q closes',
                    ]
                    draw(display, None, None, None, lines)
                    cv2.imshow(WINDOW, display)
                    displayed = True
                await asyncio.sleep(.01)
            await startup
        while True:
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), ord('Q')) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key in (ord('w'), ord('W')):
                selected = 0
            elif key in (ord('e'), ord('E')):
                selected = 1
            if not bridge and args.phase >= 2 and ord('1') <= key <= ord('4'):
                try:
                    destinations.go_to_location(robots[selected].profile.robot_id,
                                                LOCATIONS[key-ord('1')])
                except ValueError as error:
                    # A failed selection must not leave an old target driving.
                    robots[selected].gate.stop()
                    logging.warning('Destination rejected: %s', error)
            if key == ord(' '):
                if follower:
                    follower.stop(robots)
                    bridge.request_stop()
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
            world = bridge.current(now) if bridge else None
            if bridge:
                if bridge_task.done():
                    await bridge_task
                    raise RuntimeError('Backend bridge stopped')
                follower.update(robots, sample, now, world, arm=key in (ord('a'), ord('A')))
            elif key in (ord('a'), ord('A')):
                robots[selected].arm(now)
            commands = (traffic.update(robots, now, sample[1].shape[:2] if sample else None, args.phase)
                        if args.phase >= 3 else {r.profile.robot_id: r.command(now) for r in robots})
            if traffic and traffic.blocked and bridge:
                follower.stop(robots)
            if bridge:
                bridge.capture(robots, traffic)
                follower.report_arrivals(robots, world, traffic)
                if not world or follower.session != world['session_id']:
                    commands = {r.profile.robot_id:'S' for r in robots}
            elif traffic:
                for event in traffic.events:
                    logging.info('TRAFFIC: %s goes first, %s waits; detour=%s', event['winner'],event['yielder'],event['detour'])
                traffic.events.clear()
            # One lost link always stops the whole session.
            if any(r.ble and not r.ble.connected for r in robots):
                raise RuntimeError('BLE disconnected; stopping both. Restart to reconnect and re-arm.')
            results = await asyncio.gather(*(r.ble.send(commands[r.profile.robot_id]) for r in robots if r.ble),
                                           return_exceptions=True)
            errors = [result for result in results if isinstance(result, BaseException)]
            if errors:
                raise RuntimeError(f'BLE write failed; stopping both: {errors[0]}')
            lines = [f'Phase {args.phase} | selected robot: {robots[selected].profile.name}',
                     ('A enable backend tasks | SPACE stop BOTH | Q quit' if bridge else
                      'W WALL-Y | E Eeva | 1 home 2 farm 3 lake 4 market | A arm | SPACE stop | Q quit')]
            if traffic:
                lines.append('TRAFFIC: ' + traffic.reason)
                if ignore_boundary:
                    lines.append('ARENA BOUNDARY OFF | saved rectangle is reference only')
            if bridge:
                lines.append('BACKEND: ' + (bridge.error or ('armed for tasks' if follower.session else 'press A to enable tasks')))
            for robot in robots:
                ble_status = ('connected' if robot.ble.connected else 'disconnected') if robot.ble else 'off (dry run)'
                sent = robot.ble.last_command if robot.ble else 'NONE'
                lines.append(f'{robot.profile.name}: {"ARMED" if robot.gate.armed else "STOPPED"} '
                             f'BLE={ble_status} selected={commands[robot.profile.robot_id]} sent={sent} | {robot.reason}')
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
                draw_destinations(frame, config)
                for index, robot in enumerate(robots):
                    target = robot.target if args.phase >= 2 else None
                    draw(frame, robot.pose if robot.geometry else None, target, robot.geometry, [], color=COLORS[index])
                    if target:
                        cv2.putText(frame, robot.profile.name, (int(target[0]) + 15, int(target[1])),
                                    cv2.FONT_HERSHEY_SIMPLEX, .6, COLORS[index], 2)
                if traffic:
                    for robot in robots:
                        if robot.pose:
                            cv2.circle(frame, (int(robot.pose.center_x),int(robot.pose.center_y)),
                                       int(traffic.clearance(robot.profile.robot_id)), (0,0,255), 2)
                    for rect in [traffic.config.arena, *traffic.config.obstacles]:
                        cv2.rectangle(frame, (int(rect[0]),int(rect[1])), (int(rect[2]),int(rect[3])), (100,100,255), 2)
                    owner = next((r for r in robots if r.profile.robot_id==traffic.owner), None)
                    if owner and owner.pose:
                        points = [traffic.point(owner), *traffic.route]
                        for start,end in zip(points,points[1:]):
                            cv2.line(frame, tuple(map(int,start)), tuple(map(int,end)), (0,255,0), 2)
                draw(frame, None, None, None, lines)
                cv2.imshow(WINDOW, frame)
            await asyncio.sleep(.01)
    finally:
        if bridge and bridge.pending_stop is not None:
            logging.warning('Exiting with backend stop unacknowledged; stop the game in the dashboard')
        if bridge_task:
            bridge_task.cancel()
            await asyncio.gather(bridge_task, return_exceptions=True)
        if startup and not startup.done():
            startup.cancel()
            await asyncio.gather(startup, return_exceptions=True)
        for robot in robots:
            robot.gate.stop()
        # Attempt both stops concurrently before waiting for either disconnect.
        await asyncio.gather(*(r.ble.close() for r in robots if r.ble), return_exceptions=True)
        worker.stop_event.set()
        if worker.thread.is_alive():
            worker.thread.join(timeout=1)
        cv2.destroyAllWindows()
