import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
import time
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from app.config import NavigationConfig, load_navigation_config
from app.navigation.controller import MotionGate, normalize_angle, steer
from app.robots.client import BleController


class GeometryTests(unittest.TestCase):
    def test_pixel_distance_and_image_heading(self):
        pose = SimpleNamespace(center_x=100, center_y=100, heading=0)
        result = steer(pose, (400, 500), NavigationConfig())
        self.assertEqual(result.distance, 500)
        self.assertAlmostEqual(result.desired_heading, 53.130102, places=5)
        self.assertEqual(result.error, result.desired_heading)

    def test_wraparound_and_discrete_directions(self):
        config = NavigationConfig()
        pose = SimpleNamespace(center_x=100, center_y=100, heading=0)
        for target, command in [((200, 100), 'F'), ((100, 200), 'R'),
                                ((100, 0), 'L'), ((110, 100), 'S')]:
            self.assertEqual(steer(pose, target, config).command, command)
        pose.heading = 355
        self.assertEqual(steer(pose, (200, 100), config).error, 5)
        self.assertEqual(normalize_angle(181), -179)
        self.assertEqual(normalize_angle(-181), 179)
        self.assertEqual(normalize_angle(180), -180)

    def test_mount_offset_and_turn_inversion(self):
        pose = SimpleNamespace(center_x=100, center_y=100, heading=270)
        config = NavigationConfig(heading_offset_degrees=90)
        self.assertEqual(steer(pose, (200, 100), config).command, 'F')
        self.assertEqual(steer(pose, (100, 200), config).command, 'R')
        self.assertEqual(steer(pose, (100, 200), replace(config, invert_turns=True)).command, 'L')

    def test_config_limits(self):
        config = load_navigation_config(Path(__file__).resolve().parents[1] / 'navigation_config.json')
        self.assertEqual(config.ble_device, 'WALL-Y')
        for options in ({'command_hz': 100}, {'marker_timeout': 2}, {'stop_distance': float('nan')},
                        {'marker_id': 50}, {'invert_turns': 'false'}, {'pulse_seconds': .01}):
            with self.assertRaises(ValueError):
                NavigationConfig(**options)


class MotionSafetyTests(unittest.TestCase):
    def setUp(self):
        self.gate = MotionGate(NavigationConfig())

    def test_arming_pulses_and_emergency_stop_latch(self):
        self.assertEqual(self.gate.command('F', 0, 0, True, True), 'S')
        self.gate.arm(0, True)
        self.assertEqual(self.gate.command('F', .01, 0, True, True), 'F')
        self.assertEqual(self.gate.command('F', .2, .2, True, True), 'S')
        self.gate.stop()
        self.assertEqual(self.gate.command('F', .43, .43, True, True), 'S')

    def test_missing_marker_and_stale_camera_latch(self):
        self.gate.arm(0, True)
        self.assertEqual(self.gate.command('F', .05, 0, False, True), 'S')
        self.assertEqual(self.gate.command('F', .5, 0, True, True), 'S')
        self.assertFalse(self.gate.armed)
        self.assertEqual(self.gate.command('F', .6, .6, True, True), 'S')

    def test_disconnect_and_arrival_require_rearm(self):
        self.gate.arm(0, True)
        self.assertEqual(self.gate.command('R', .01, 0, True, False), 'S')
        self.assertFalse(self.gate.armed)
        self.gate.arm(0, True)
        self.assertEqual(self.gate.command('S', .01, 0, True, True), 'S')
        self.assertFalse(self.gate.armed)
        self.gate.arm(0, False)
        self.assertFalse(self.gate.armed)


class BleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 0
        self.config = NavigationConfig(ble_device='WALL-Y', ble_characteristic='test-uuid')
        self.device = SimpleNamespace(name='WALL-Y', address='macos-uuid')
        self.client = SimpleNamespace(is_connected=True, connect=AsyncMock(),
                                      write_gatt_char=AsyncMock(), disconnect=AsyncMock())
        self.scanner = SimpleNamespace(discover=AsyncMock(return_value=[self.device]))
        self.factory = Mock(return_value=self.client)
        self.ble = BleController(self.config, client_factory=self.factory,
                                 scanner=self.scanner, clock=lambda: self.now)
        await self.ble.connect()

    async def test_connect_stop_rate_limit_refresh_and_priority_stop(self):
        self.client.write_gatt_char.assert_awaited_once_with('test-uuid', b'S', response=True)
        self.factory.assert_called_once_with(self.device, disconnected_callback=self.ble._disconnected)
        self.now = .11
        self.assertTrue(await self.ble.send('F'))
        self.now = .12
        self.assertFalse(await self.ble.send('R'))
        self.now = .22
        self.assertFalse(await self.ble.send('F'))
        self.now = .42
        self.assertTrue(await self.ble.send('F'))
        self.now = .43
        self.assertTrue(await self.ble.send('S'))
        await self.ble.close()
        self.assertEqual(self.client.write_gatt_char.await_args.args[1], b'S')
        self.client.disconnect.assert_awaited_once()

    async def test_disconnect_prevents_more_motion(self):
        self.ble._disconnected(self.client)
        with self.assertRaises(RuntimeError):
            await self.ble.send('F')
        self.assertFalse(self.ble.connected)

    async def test_write_failure_stops_and_disconnects(self):
        self.now = 1
        self.client.write_gatt_char.side_effect = RuntimeError('link error')
        with self.assertRaises(RuntimeError):
            await self.ble.send('F')
        self.assertFalse(self.ble.connected)
        await self.ble.close()
        self.client.disconnect.assert_awaited_once()
        self.assertEqual(self.client.write_gatt_char.await_args.args[1], b'S')

    async def test_write_timeout_is_bounded_and_faults(self):
        self.now = 1

        async def stalled(*args, **kwargs):
            await asyncio.sleep(10)

        self.client.write_gatt_char.side_effect = stalled
        with self.assertRaises(TimeoutError):
            await self.ble.send('F')
        self.assertFalse(self.ble.connected)


class PhaseLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_phases_one_to_three_never_connect_or_send(self):
        from app.navigation.__main__ import run
        for phase in (1, 2, 3):
            worker = Mock()
            worker.error = None
            worker.done = False
            worker.snapshot.return_value = (time.monotonic(), np.zeros((400, 600, 3), np.uint8),
                                           SimpleNamespace(marker_id=0, center_x=100,
                                                           center_y=100, heading=0))
            worker.thread.is_alive.return_value = False
            with patch('app.navigation.__main__.CameraWorker', return_value=worker), \
                    patch('app.navigation.__main__.BleController') as ble, \
                    patch('app.navigation.__main__.cv2') as cv:
                cv.waitKey.side_effect = [-1, ord('q')]
                cv.getWindowProperty.return_value = 1
                await run(SimpleNamespace(phase=phase, video=None, camera=0), NavigationConfig())
                ble.assert_not_called()
                cv.imshow.assert_called_once()
                worker.stop_event.set.assert_called_once()

    async def test_phase_four_space_and_exit_stop(self):
        from app.navigation.__main__ import run
        worker = Mock()
        worker.error, worker.done = None, False
        worker.snapshot.return_value = (time.monotonic(), np.zeros((400, 600, 3), np.uint8),
                                       SimpleNamespace(marker_id=0, center_x=100, center_y=100, heading=0))
        worker.thread.is_alive.return_value = False
        ble = SimpleNamespace(connected=True, last_command='S', connect=AsyncMock(),
                              send=AsyncMock(), close=AsyncMock())
        with patch('app.navigation.__main__.CameraWorker', return_value=worker), \
                patch('app.navigation.__main__.BleController', return_value=ble), \
                patch('app.navigation.__main__.cv2') as cv:
            cv.waitKey.side_effect = [-1, ord('a'), ord(' '), ord('q')]
            cv.getWindowProperty.return_value = 1
            await run(SimpleNamespace(phase=4, video=None, camera=0), NavigationConfig())
        self.assertEqual(ble.send.await_args_list[0].args, ('S',))
        self.assertIn(ble.send.await_args_list[1].args[0], ('F', 'L', 'R'))
        ble.send.assert_any_await('S', force=True)
        ble.close.assert_awaited_once()

    async def test_stalled_camera_disarms_even_when_marker_was_last_visible(self):
        from app.navigation.__main__ import run
        worker = Mock()
        worker.error, worker.done = None, False
        worker.thread.is_alive.return_value = False
        pose = SimpleNamespace(marker_id=0, center_x=100, center_y=100, heading=0)
        samples = iter([(time.monotonic(), np.zeros((400, 600, 3), np.uint8), pose),
                        (time.monotonic() - 1, np.zeros((400, 600, 3), np.uint8), pose),
                        (time.monotonic(), np.zeros((400, 600, 3), np.uint8), pose)])
        worker.snapshot.side_effect = lambda: next(samples)
        ble = SimpleNamespace(connected=True, last_command='S', connect=AsyncMock(),
                              send=AsyncMock(), close=AsyncMock())
        with patch('app.navigation.__main__.CameraWorker', return_value=worker), \
                patch('app.navigation.__main__.BleController', return_value=ble), \
                patch('app.navigation.__main__.cv2') as cv:
            cv.waitKey.side_effect = [ord('a'), -1, ord('q')]
            cv.getWindowProperty.return_value = 1
            await run(SimpleNamespace(phase=4, video=None, camera=0), NavigationConfig())
        self.assertNotEqual(ble.send.await_args_list[0].args, ('S',))
        self.assertEqual(ble.send.await_args_list[1].args, ('S',))
        ble.close.assert_awaited_once()

    async def test_camera_failure_still_closes_ble(self):
        from app.navigation.__main__ import run
        worker = Mock()
        worker.error = RuntimeError('camera unavailable')
        worker.thread.is_alive.return_value = False
        ble = SimpleNamespace(connect=AsyncMock(), close=AsyncMock())
        with patch('app.navigation.__main__.CameraWorker', return_value=worker), \
                patch('app.navigation.__main__.BleController', return_value=ble), \
                patch('app.navigation.__main__.cv2'):
            with self.assertRaisesRegex(RuntimeError, 'Camera failed'):
                await run(SimpleNamespace(phase=4, video=None, camera=0), NavigationConfig())
        ble.close.assert_awaited_once()
        worker.stop_event.set.assert_called_once()


if __name__ == '__main__':
    unittest.main()
