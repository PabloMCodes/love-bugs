import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from app.config import NavigationConfig, NavigationRobot, load_navigation_robots
from app.navigation.fleet import RobotControl, discover_fleet_devices, run_fleet, stop_all
from app.navigation.__main__ import CameraWorker
from app.robots.client import BleController
from test_vision import frame_with_markers


def profiles():
    return tuple(NavigationRobot(robot_id, name, NavigationConfig(marker_id=index,
                 ble_device=name, ble_characteristic='command', ble_write_response=False))
                 for index, (robot_id, name) in enumerate((('robot-a', 'WALL-Y'), ('robot-b', 'Eeva'))))


def pose(index):
    return SimpleNamespace(marker_id=index, center_x=100, center_y=100, heading=0)


def sample(poses, captured=None):
    return (time.monotonic() if captured is None else captured,
            np.zeros((400, 600, 3), np.uint8), poses)


class FleetStateTests(unittest.TestCase):
    def test_camera_worker_routes_both_marker_ids(self):
        source = Mock()
        source.live = True
        source.read.side_effect = [(True, frame_with_markers([(0, 40, 40, 0), (1, 440, 240, 1)])),
                                   (False, None)]
        source.capture.get.return_value = 30
        with patch('app.navigation.__main__.VideoSource') as factory:
            factory.return_value.__enter__.return_value = source
            worker = CameraWorker(0, profiles()[0].config, robots=profiles())
            worker.run()
        self.assertIsNone(worker.error)
        self.assertTrue(worker.done)
        observed = worker.snapshot()[2]
        self.assertEqual(set(observed), {'robot-a', 'robot-b'})
        self.assertEqual(observed['robot-a'].marker_id, 0)
        self.assertEqual(observed['robot-b'].marker_id, 1)

    def test_profiles_and_duplicate_identity_rejection(self):
        path = Path(__file__).resolve().parents[1] / 'navigation_robots.json'
        loaded = load_navigation_robots(path)
        self.assertEqual([p.config.marker_id for p in loaded], [0, 1])
        self.assertEqual([p.config.ble_device for p in loaded], ['WALL-Y', 'Eeva'])
        self.assertTrue(all(not p.config.ble_direct_address for p in loaded))
        self.assertTrue(all(not p.config.ble_write_response for p in loaded))
        original = json.loads(path.read_text())
        for field in ('marker_id', 'ble_device'):
            data = json.loads(json.dumps(original))
            data['robot-b'][field] = data['robot-a'][field]
            with tempfile.TemporaryDirectory() as directory:
                invalid = Path(directory) / 'invalid.json'
                invalid.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    load_navigation_robots(invalid)

    def test_independent_targets_calibration_and_marker_loss(self):
        a, b = [RobotControl(p, 3) for p in profiles()]
        for r in (a, b):
            r.ble = SimpleNamespace(connected=True)
        a.set_target(300, 100)
        b.set_target(100, 300)
        both = sample({'robot-a': pose(0), 'robot-b': pose(1)}, 10)
        for r in (a, b):
            r.observe(both, 10, 4)
            r.arm(10)
        self.assertEqual(a.command(10), 'F')
        self.assertEqual(b.command(10), 'R')
        b.config = replace(b.config, heading_offset_degrees=90)
        b.observe(both, 10, 4)
        self.assertEqual(b.desired, 'F')
        # Only WALL-Y loses tracking; Eeva's pose and arming remain independent.
        only_b = sample({'robot-b': pose(1)}, 10.6)
        for r in (a, b):
            r.observe(only_b, 10.6, 4)
            r.command(10.6)
        self.assertFalse(a.gate.armed)
        self.assertTrue(b.gate.armed)
        a.set_target(500, 100)
        self.assertEqual(b.target, (100, 300))
        self.assertTrue(b.gate.armed)


class FleetBleTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_scan_resolves_both_names(self):
        devices = [SimpleNamespace(name='WALL-Y', address='wall-uuid'),
                   SimpleNamespace(name='Eeva', address='eeva-uuid')]
        scanner = SimpleNamespace(discover=AsyncMock(return_value=devices))
        resolved = await discover_fleet_devices(profiles(), scanner=scanner)
        scanner.discover.assert_awaited_once_with(timeout=10)
        self.assertIs(resolved['robot-a'], devices[0])
        self.assertIs(resolved['robot-b'], devices[1])

    async def test_fleet_scan_reports_missing_robot_and_visible_devices(self):
        scanner = SimpleNamespace(discover=AsyncMock(return_value=[
            SimpleNamespace(name='WALL-Y', address='wall-uuid'),
        ]))
        with self.assertRaisesRegex(RuntimeError, "Eeva.*Visible devices.*WALL-Y"):
            await discover_fleet_devices(profiles(), scanner=scanner)

    async def test_direct_identifiers_and_unacknowledged_writes(self):
        client = SimpleNamespace(is_connected=True, connect=AsyncMock(),
                                 write_gatt_char=AsyncMock(), disconnect=AsyncMock())
        scanner = SimpleNamespace(discover=AsyncMock())
        factory = Mock(return_value=client)
        config = replace(profiles()[0].config, ble_direct_address=True)
        ble = BleController(config, client_factory=factory, scanner=scanner)
        await ble.connect()
        self.assertEqual(factory.call_args.args, ('WALL-Y',))
        scanner.discover.assert_not_called()
        client.write_gatt_char.assert_awaited_with('command', b'S', response=False)
        await ble.close()

    async def test_stop_attempts_both_even_if_one_link_fails(self):
        robots = [RobotControl(p, 3) for p in profiles()]
        for r in robots:
            r.gate.arm(10, True)
            r.ble = SimpleNamespace(send=AsyncMock())
        robots[0].ble.send.side_effect = RuntimeError('link failed')
        await stop_all(robots)
        for r in robots:
            self.assertFalse(r.gate.armed)
            r.ble.send.assert_awaited_once_with('S', force=True)

    async def run_ui(self, keys, phase=4, connect_error=False):
        worker = Mock(error=None, done=False)
        worker.snapshot.side_effect = lambda: sample({'robot-a': pose(0), 'robot-b': pose(1)})
        worker.thread.is_alive.return_value = False
        clients = [SimpleNamespace(connected=True, last_command='S', connect=AsyncMock(),
                                   send=AsyncMock(), close=AsyncMock()) for _ in range(2)]
        if connect_error:
            clients[1].connect.side_effect = RuntimeError('second connection failed')
        with patch('app.navigation.fleet.CameraWorker', return_value=worker), \
                patch('app.navigation.fleet.BleController', side_effect=clients) as factory, \
                patch('app.navigation.fleet.discover_fleet_devices', new_callable=AsyncMock,
                      return_value={'robot-a': SimpleNamespace(address='wall-uuid'),
                                    'robot-b': SimpleNamespace(address='eeva-uuid')}) as discover, \
                patch('app.navigation.fleet.cv2') as cv, \
                patch('app.navigation.fleet.draw'):
            cv.EVENT_LBUTTONDOWN = 1
            cv.getWindowProperty.return_value = 1
            actions = iter(keys)

            def keypress(_delay):
                value = next(actions)
                if isinstance(value, tuple):
                    cv.setMouseCallback.call_args.args[1](1, *value, 0, None)
                    return -1
                return ord(value)

            cv.waitKey.side_effect = keypress
            if connect_error:
                with self.assertRaisesRegex(RuntimeError, 'second connection'):
                    await run_fleet(SimpleNamespace(phase=phase, video=None, camera=0), profiles())
            else:
                await run_fleet(SimpleNamespace(phase=phase, video=None, camera=0), profiles())
            if phase < 4:
                factory.assert_not_called()
                discover.assert_not_awaited()
            else:
                discover.assert_awaited_once()
                clients[0].connect.assert_awaited_once()
                clients[1].connect.assert_awaited_once()
                self.assertEqual(clients[0].connect.await_args.kwargs['device'].address, 'wall-uuid')
                self.assertEqual(clients[1].connect.await_args.kwargs['device'].address, 'eeva-uuid')
        return clients

    async def test_ui_routes_clicks_arms_independently_and_stops_both(self):
        clients = await self.run_ui([(300, 100), 'a', 'e', (100, 300), 'a', ' ', 'q'])
        a_commands = [c.args[0] for c in clients[0].send.await_args_list]
        b_commands = [c.args[0] for c in clients[1].send.await_args_list]
        self.assertIn('F', a_commands)
        self.assertNotIn('R', a_commands)
        self.assertIn('R', b_commands)
        self.assertNotIn('F', b_commands)
        for client in clients:
            client.send.assert_any_await('S', force=True)
            client.close.assert_awaited_once()

    async def test_second_connection_failure_cleans_up_both(self):
        clients = await self.run_ui([], connect_error=True)
        for client in clients:
            client.close.assert_awaited_once()

    async def test_dry_phases_never_connect(self):
        for phase in (1, 2, 3):
            await self.run_ui(['w', (300, 100), 'e', (100, 300), 'a', 'q'], phase=phase)


if __name__ == '__main__':
    unittest.main()
