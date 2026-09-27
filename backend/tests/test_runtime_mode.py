from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AgentConfig, Settings
from app.main import create_app


class RuntimeModeTests(unittest.TestCase):
    def settings(self, directory, mode):
        return Settings(
            database_url=None,
            sqlite_path=str(Path(directory) / 'mode.sqlite3'),
            game_mode=mode,
        )

    def test_settings_load_and_validate_game_mode(self):
        with patch.dict('os.environ', {
            'GAME_MODE': ' HARDWARE ',
            'AUTONOMY_ENABLED': 'true',
            'AUTONOMY_PROVIDER': ' GEMINI ',
        }):
            settings = Settings()
            self.assertEqual(settings.game_mode, 'hardware')
            self.assertTrue(settings.autonomy_enabled)
            self.assertEqual(settings.autonomy_provider, 'gemini')

        with self.assertRaisesRegex(ValueError, 'GAME_MODE'):
            Settings(game_mode='unsupported')
        with self.assertRaisesRegex(ValueError, 'AUTONOMY_ENABLED'):
            Settings(autonomy_enabled='true')
        with self.assertRaisesRegex(ValueError, 'AUTONOMY_PROVIDER'):
            Settings(autonomy_provider='unsupported')
        with patch.dict('os.environ', {'AUTONOMY_ENABLED': 'sometimes'}):
            with self.assertRaisesRegex(ValueError, 'AUTONOMY_ENABLED'):
                Settings()
        with self.assertRaisesRegex(ValueError, 'Telemetry'):
            Settings(health_timeout_seconds=0)

    def test_simulation_mode_is_default_and_starts_simulator(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(settings=self.settings(directory, 'simulation'))
            with TestClient(app) as client:
                world = client.get('/world').json()

            self.assertEqual(world['mode'], 'simulation')
            self.assertTrue(app.state.simulator_enabled)
            self.assertFalse(app.state.telemetry_watchdog_enabled)
            self.assertTrue(all(robot['physical']['pose'] for robot in world['robots']))

    def test_explicit_override_can_disable_simulator_for_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(
                settings=self.settings(directory, 'simulation'),
                run_simulator=False,
            )
            with TestClient(app):
                self.assertFalse(app.state.simulator_enabled)
                self.assertFalse(app.state.game_loop_enabled)
                self.assertFalse(app.state.autonomy_enabled)

    def test_backend_mock_autonomy_assigns_tasks_without_chat_round(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_url=None,
                sqlite_path=str(Path(directory) / 'autonomy.sqlite3'),
                game_mode='simulation',
                autonomy_enabled=True,
                autonomy_provider='mock',
            )
            app = create_app(
                settings=settings,
                agent_config=AgentConfig(
                    interval_seconds=.01,
                    timeout_seconds=1,
                ),
            )
            with TestClient(app) as client:
                self.assertTrue(app.state.autonomy_enabled)
                self.assertIsNotNone(app.state.orchestrator)
                self.assertEqual(
                    client.get('/agent-chat').json()['mode'],
                    'autonomous',
                )

                client.post('/game/start').raise_for_status()
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    tasks = client.get('/tasks').json()['tasks']
                    conversation = client.get('/agent-chat').json()
                    if len(tasks) >= 2 and len(conversation['messages']) >= 2:
                        break
                    time.sleep(.01)
                else:
                    self.fail('Backend autonomy did not assign tasks')

                self.assertEqual(
                    {task['action'] for task in tasks[:2]},
                    {'HARVEST', 'FISH'},
                )
                self.assertTrue(
                    all(message['status'] == 'accepted'
                        for message in conversation['messages'][:2])
                )
                rejected = client.post('/agent-chat/round', json={
                    'provider': 'mock',
                    'world': client.get('/world').json(),
                })
                self.assertEqual(rejected.status_code, 409)

                stopped = client.post('/game/stop').json()
                self.assertEqual(stopped['game']['status'], 'STOPPED')
                task_count = len(client.get('/tasks').json()['tasks'])
                time.sleep(.05)
                self.assertEqual(
                    len(client.get('/tasks').json()['tasks']),
                    task_count,
                )

    def test_hardware_mode_waits_for_real_telemetry_and_never_simulates(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(settings=self.settings(directory, 'hardware'))
            with TestClient(app) as client:
                initial = client.get('/world').json()
                billy = initial['robots'][0]

                self.assertEqual(initial['mode'], 'hardware')
                self.assertFalse(app.state.simulator_enabled)
                self.assertTrue(app.state.game_loop_enabled)
                self.assertTrue(app.state.telemetry_watchdog_enabled)
                self.assertFalse(billy['physical']['online'])
                self.assertIsNone(billy['physical']['pose'])
                self.assertIsNone(billy['physical']['pose_updated_at'])
                self.assertEqual(billy['physical']['tracking'], 'UNKNOWN')
                self.assertIsNone(billy['physical']['battery'])
                self.assertIsNone(billy['game']['location'])

                client.post('/game/start').raise_for_status()
                unavailable = client.post('/tasks', json={
                    'request_id': 'hardware-before-telemetry',
                    'robot_id': 'robot-a',
                    'action': 'MOVE_TO',
                    'location': 'farm',
                    'parameters': {},
                })
                self.assertEqual(unavailable.status_code, 409)
                self.assertEqual(
                    unavailable.json()['error']['code'],
                    'ROBOT_UNAVAILABLE',
                )

                session_id = initial['session_id']
                health = client.post('/robots/robot-a/health', json={
                    'session_id': session_id,
                    'online': True,
                    'battery': .75,
                    'blocked': False,
                })
                pose = client.post('/robots/robot-a/pose', json={
                    'session_id': session_id,
                    'pose': {'x': 12, 'y': 30, 'heading': 0},
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                })
                self.assertEqual(health.json(), {'accepted': True})
                self.assertEqual(pose.json(), {'accepted': True})

                assigned = client.post('/tasks', json={
                    'request_id': 'hardware-after-telemetry',
                    'robot_id': 'robot-a',
                    'action': 'MOVE_TO',
                    'location': 'farm',
                    'parameters': {},
                })
                self.assertEqual(assigned.status_code, 202)
                time.sleep(.35)
                unchanged = client.get('/world').json()['robots'][0]
                self.assertEqual(unchanged['task']['status'], 'ASSIGNED')
                self.assertEqual(
                    unchanged['physical']['pose'],
                    {'x': 12, 'y': 30, 'heading': 0},
                )

    def test_hardware_mode_runs_game_timers_after_real_arrival(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(
                settings=self.settings(directory, 'hardware'),
                run_simulator=False,
            )
            with TestClient(app) as client:
                initial = client.get('/world').json()
                session_id = initial['session_id']
                client.post('/robots/robot-a/health', json={
                    'session_id': session_id,
                    'online': True,
                    'battery': .75,
                    'blocked': False,
                }).raise_for_status()
                client.post('/robots/robot-a/pose', json={
                    'session_id': session_id,
                    'pose': {'x': 12, 'y': 30, 'heading': 0},
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }).raise_for_status()
                client.post('/game/start').raise_for_status()
                task = client.post('/tasks', json={
                    'request_id': 'hardware-fishing',
                    'robot_id': 'robot-a',
                    'action': 'FISH',
                    'location': 'lake',
                    'parameters': {},
                }).json()
                client.post('/robots/robot-a/arrived', json={
                    'session_id': session_id,
                    'task_id': task['id'],
                    'location': 'lake',
                }).raise_for_status()

                before = client.get('/world').json()['robots'][0]
                for _ in range(10):
                    app.state.simulator.tick()
                completed = client.get('/world').json()['robots'][0]

                self.assertEqual(before['task']['status'], 'ACTIVE')
                self.assertIsNone(completed['task'])
                self.assertEqual(
                    completed['game']['inventory']['fish']['quantity'],
                    before['game']['inventory'].get('fish', {}).get('quantity', 0) + 1,
                )
                self.assertEqual(
                    completed['physical']['pose'],
                    before['physical']['pose'],
                )

    def test_hardware_watchdog_expires_missing_reports_automatically(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_url=None,
                sqlite_path=str(Path(directory) / 'watchdog.sqlite3'),
                game_mode='hardware',
                health_timeout_seconds=.05,
                pose_timeout_seconds=.05,
                telemetry_check_interval_seconds=.01,
            )
            app = create_app(settings=settings)
            with TestClient(app) as client:
                initial = client.get('/world').json()
                session_id = initial['session_id']
                client.post('/robots/robot-a/health', json={
                    'session_id': session_id,
                    'online': True,
                    'battery': .8,
                    'blocked': False,
                }).raise_for_status()
                client.post('/robots/robot-a/pose', json={
                    'session_id': session_id,
                    'pose': {'x': 12, 'y': 30, 'heading': 0},
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }).raise_for_status()

                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    billy = client.get('/world').json()['robots'][0]
                    if (
                        not billy['physical']['online']
                        and billy['physical']['tracking'] == 'STALE'
                    ):
                        break
                    time.sleep(.01)
                else:
                    self.fail('Telemetry watchdog did not expire missing reports')

                event_types = [
                    event['type']
                    for event in client.get('/events').json()['events']
                ]
                self.assertIn('robot_offline', event_types)
                self.assertIn('tracking_stale', event_types)


if __name__ == '__main__':
    unittest.main()
