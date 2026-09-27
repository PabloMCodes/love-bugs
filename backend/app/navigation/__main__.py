"""Incremental click-to-drive demo with optional fleet traffic and hardware task bridge."""

import argparse
import asyncio
import logging
from math import cos, radians, sin
from pathlib import Path
import threading
import time

import cv2

from app.config import VisionConfig, load_navigation_config, load_navigation_robots
from app.navigation.controller import MotionGate, steer
from app.robots.client import BleController
from app.vision.capture import VideoSource
from app.vision.localization import ArucoTracker

WINDOW = 'WALL-Y navigation'


class CameraWorker:
    """A blocked camera read must not block BLE stop or the keyboard UI.

    Keep only the latest processed frame. Timestamp before read/detection so
    slow acquisition is treated as stale, not as a newly localized robot.
    """

    def __init__(self, source, config, *, robots=None):
        self.source, self.config = source, config
        self.robots = robots
        self.lock = threading.Lock()
        self.latest = None
        self.error = None
        self.done = False
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        try:
            mapping = ({r.config.marker_id: r.robot_id for r in self.robots} if self.robots
                       else {self.config.marker_id: 'robot-a'})
            tracker = ArucoTracker(VisionConfig(mapping, ()))
            with VideoSource(self.source) as source:
                fps = source.capture.get(cv2.CAP_PROP_FPS)
                interval = 1 / fps if 0 < fps < 240 else 1 / 30
                while not self.stop_event.is_set():
                    captured = time.monotonic()
                    running, frame = source.read()
                    if not running:
                        break
                    if frame is None:
                        self.stop_event.wait(.03)
                        continue
                    poses, _ = tracker.process(frame, draw=True)
                    pose = ({p.robot_id: p for p in poses if p.marker_id in mapping} if self.robots
                            else next((p for p in poses if p.marker_id == self.config.marker_id), None))
                    with self.lock:
                        self.latest = (captured, frame, pose)
                    if not source.live:
                        self.stop_event.wait(max(0, interval - (time.monotonic() - captured)))
        except Exception as error:
            self.error = error
        finally:
            self.done = True

    def snapshot(self):
        with self.lock:
            return self.latest


def draw(frame, pose, target, geometry, lines, *, color=(255, 0, 255)):
    if target is not None:
        point = tuple(round(v) for v in target)
        cv2.drawMarker(frame, point, color, cv2.MARKER_CROSS, 24, 2)
        cv2.circle(frame, point, 12, color, 2)
        if pose is not None:
            origin = (round(pose.center_x), round(pose.center_y))
            cv2.line(frame, origin, point, color, 1)
            heading = radians(geometry.heading)
            tip = (round(origin[0] + 60 * cos(heading)), round(origin[1] + 60 * sin(heading)))
            cv2.arrowedLine(frame, origin, tip, (0, 255, 255), 2)
    for index, line in enumerate(lines):
        position = (10, 25 + index * 24)
        cv2.putText(frame, line, position, cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 0), 4)
        cv2.putText(frame, line, position, cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 1)


async def run(args, config):
    target = [config.target_x, config.target_y]
    gate = MotionGate(config)
    ble = BleController(config) if args.phase == 4 else None
    worker = CameraWorker(args.video if args.video else
                          (args.camera if args.camera is not None else config.camera_index), config)
    last_seen = None
    last_log = float('-inf')
    last_frame = None
    last_desired = None
    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)

    def click(event, x, y, _flags, _data):
        if event == cv2.EVENT_LBUTTONDOWN and args.phase >= 2:
            target[:] = [x, y]
            gate.stop()  # A new destination requires an explicit A in phase 4.
            logging.info('Target: (%s, %s); press A to arm phase 4', x, y)

    cv2.setMouseCallback(WINDOW, click)
    try:
        if ble:
            await ble.connect()
        worker.thread.start()
        while True:
            now = time.monotonic()
            sample = worker.snapshot()
            if worker.error:
                raise RuntimeError(f'Camera failed: {worker.error}')
            if worker.done:
                logging.info('Video ended')
                break
            pose = None
            if sample:
                captured, frame, observed = sample
                if captured != last_frame:
                    last_frame = captured
                    if observed is not None:
                        last_seen = captured
                if now - captured < config.marker_timeout:
                    pose = observed
            geometry = steer(pose, tuple(target), config) if pose and args.phase >= 2 else None
            target_valid = bool(sample and 0 <= target[0] < sample[1].shape[1]
                                and 0 <= target[1] < sample[1].shape[0])
            desired = geometry.command if geometry and target_valid and args.phase >= 3 else 'S'
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                gate.stop()
                break
            if key == ord(' '):
                gate.stop()
                if ble:
                    await ble.send('S', force=True)
                logging.info('EMERGENCY STOP latched; A required to re-arm')
            elif key == ord('a') and ble:
                gate.arm(now, pose is not None and target_valid and ble.connected)
            command = gate.command(desired, now, last_seen, pose is not None,
                                   ble.connected if ble else True) if ble else 'S'
            if ble:
                await ble.send(command)
            lines = [f'Phase {args.phase} | selected={desired} | sent={ble.last_command if ble else "NONE (dry run)"}',
                     f'BLE: {"connected" if ble and ble.connected else "disabled"} | {"ARMED" if gate.armed else "STOPPED"}',
                     'Click target | A arm | SPACE stop | Q quit']
            if pose:
                lines.append(f'ID={pose.marker_id} x={pose.center_x:.1f} y={pose.center_y:.1f} marker h={pose.heading:.1f}')
            else:
                lines.append('MARKER MISSING / STALE - STOP')
            if geometry:
                lines.append(f'd={geometry.distance:.1f}px desired={geometry.desired_heading:.1f} '
                             f'heading={geometry.heading:.1f} error={geometry.error:+.1f}')
            if args.phase >= 2 and not target_valid:
                lines.append('TARGET OUTSIDE FRAME - click a valid target')
            if now - last_log >= .5 or desired != last_desired:
                logging.info(' | '.join(lines[:2] + lines[3:]))
                last_log, last_desired = now, desired
            if sample:
                display = sample[1].copy()
                draw(display, pose, tuple(target) if args.phase >= 2 else None, geometry, lines)
                cv2.imshow(WINDOW, display)
            await asyncio.sleep(.01)
    finally:
        gate.stop()
        if ble:
            await ble.close()
        worker.stop_event.set()
        if worker.thread.is_alive():
            worker.thread.join(timeout=1)
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[2] / 'navigation_config.json')
    parser.add_argument('--robots-config', type=Path,
                        help='Two-robot JSON profiles; enables W/E selection and independent targets')
    parser.add_argument('--traffic-config', type=Path, help='Calibrated fleet collision/detour configuration')
    parser.add_argument('--backend-url', help='Hardware backend URL; enables task/pose/chat bridge')
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument('--camera', type=int)
    sources.add_argument('--video')
    args = parser.parse_args()
    if args.phase == 4 and args.video:
        parser.error('Phase 4 requires a live camera; prerecorded poses cannot control hardware')
    if (args.traffic_config or args.backend_url) and not args.robots_config:
        parser.error('Traffic and backend integration require --robots-config')
    if args.backend_url and (not args.traffic_config or args.phase != 4):
        parser.error('--backend-url requires --traffic-config and phase 4')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        if args.robots_config:
            from app.navigation.fleet import run_fleet
            logging.info('Loading robot configuration: %s', args.robots_config.resolve())
            asyncio.run(run_fleet(args, load_navigation_robots(args.robots_config)))
        else:
            asyncio.run(run(args, load_navigation_config(args.config)))
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        logging.error('%s: %s', type(error).__name__, error or repr(error))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
