from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import (
    AgentConfig,
    DEFAULT_GAME_PROFILE,
    Settings,
    default_game_profile,
)
from app.main import create_app
from app.state import WorldStore, default_world


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

    def test_game_profile_configures_service_points_and_progression(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = deepcopy(DEFAULT_GAME_PROFILE)
            profile['starting_gold_per_robot'] = 25
            profile['victory_target'] = 175
            profile['plot_count'] = 4
            profile['map']['width'] = 12
            profile['map']['height'] = 8
            profile['map']['locations'] = {
                'homebase': {'x': 1, 'y': 1},
                'farm': {'x': 3, 'y': 2},
                'lake': {'x': 6, 'y': 4},
                'market': {'x': 10, 'y': 7},
            }
            profile['crops'][0]['grow_seconds'] = .01
            path = Path(directory) / 'game.json'
            path.write_text(json.dumps(profile))

            settings = Settings(
                database_url=None,
                sqlite_path=str(Path(directory) / 'profile.sqlite3'),
                game_config_path=str(path),
            )
            app = create_app(settings=settings, run_simulator=False)
            with TestClient(app) as client:
                world = client.get('/world').json()

            self.assertEqual(world['map'], profile['map'])
            self.assertEqual(world['game']['goal'], {
                'type': 'earn_gold', 'target': 175, 'current': 50,
            })
            self.assertEqual(len(world['farm']['plots']), 4)
            self.assertEqual(world['farm']['crops'][0]['grow_seconds'], .01)
            self.assertEqual(
                [(robot['physical']['pose']['x'], robot['physical']['pose']['y'])
                 for robot in world['robots']],
                [(1, 1), (1, 1)],
            )

            profile['map']['locations']['market']['x'] = 13
            path.write_text(json.dumps(profile))
            with self.assertRaisesRegex(ValueError, 'inside the configured map'):
                Settings(game_config_path=str(path))

    def test_committed_game_profile_matches_built_in_default(self):
        profile_path = Path(__file__).parents[1] / 'game_config.json'
        committed = json.loads(profile_path.read_text())
        self.assertEqual(
            committed,
            default_game_profile().model_dump(mode='json'),
        )

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

    def test_game_loop_marks_elapsed_crop_ready_without_manual_tick(self):
        world = default_world()
        planted_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        world['farm']['plots'][0].update({
            'status': 'GROWING',
            'crop_id': 'wheat',
            'planted_by': 'robot-a',
            'planted_at': planted_at,
            'ready_at': planted_at + timedelta(milliseconds=50),
        })
        app = create_app(
            world_store=WorldStore(world),
            run_simulator=True,
        )

        with TestClient(app) as client:
            client.post('/game/start').raise_for_status()
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                current = client.get('/world').json()
                if current['farm']['plots'][0]['status'] == 'READY':
                    break
                time.sleep(.01)
            else:
                self.fail('Backend game loop did not mark the crop ready')

        self.assertEqual(current['events'][-1]['type'], 'crop_ready')

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
                    {'BUY'},
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
                catch_id = task['parameters']['catch']['item_id']
                client.post('/robots/robot-a/arrived', json={
                    'session_id': session_id,
                    'task_id': task['id'],
                    'location': 'lake',
                }).raise_for_status()

                before = client.get('/world').json()['robots'][0]
                for _ in range(61):
                    app.state.simulator.tick()
                completed = client.get('/world').json()['robots'][0]

                self.assertEqual(before['task']['status'], 'ACTIVE')
                self.assertIsNone(completed['task'])
                self.assertEqual(
                    completed['game']['inventory'][catch_id]['quantity'],
                    before['game']['inventory'].get(catch_id, {}).get('quantity', 0) + 1,
                )
                self.assertEqual(
                    completed['physical']['pose'],
                    before['physical']['pose'],
                )

    def test_hardware_input_drives_complete_crop_market_loop_exactly_once(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = deepcopy(DEFAULT_GAME_PROFILE)
            profile['crops'][0]['grow_seconds'] = .01
            profile['starting_gold_per_robot'] = 10
            profile['victory_target'] = 40
            profile['market_items'][1]['unlock_at'] = 20
            profile['market_items'][2]['unlock_at'] = 18
            profile['stage_unlocks'][0].update({
                'eligibility_gold': 20,
                'cost': 2,
            })
            profile['stage_unlocks'][1].update({
                'eligibility_gold': 18,
                'cost': 2,
            })
            profile_path = Path(directory) / 'hardware-game.json'
            profile_path.write_text(json.dumps(profile))
            settings = Settings(
                database_url=None,
                sqlite_path=str(Path(directory) / 'hardware-loop.sqlite3'),
                game_mode='hardware',
                game_config_path=str(profile_path),
            )
            app = create_app(settings=settings, run_simulator=False)

            with TestClient(app) as client:
                initial = client.get('/world').json()
                session_id = initial['session_id']
                original_pose = {'x': 50, 'y': 30, 'heading': 0}
                client.post('/robots/robot-a/health', json={
                    'session_id': session_id,
                    'online': True,
                    'battery': .75,
                    'blocked': False,
                }).raise_for_status()
                client.post('/robots/robot-a/pose', json={
                    'session_id': session_id,
                    'pose': original_pose,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }).raise_for_status()
                client.post('/robots/robot-b/health', json={
                    'session_id': session_id,
                    'online': True,
                    'battery': .8,
                    'blocked': False,
                }).raise_for_status()
                client.post('/robots/robot-b/pose', json={
                    'session_id': session_id,
                    'pose': {'x': 50, 'y': 30, 'heading': 180},
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }).raise_for_status()
                client.post('/game/start').raise_for_status()

                for stage in (2, 3):
                    proposal_response = client.post(
                        '/economy/unlock-proposals',
                        json={
                            'request_id': f'hardware-stage-{stage}',
                            'proposer_id': 'robot-a',
                            'stage': stage,
                            'contributions': {'robot-a': 1, 'robot-b': 1},
                        },
                    )
                    self.assertEqual(
                        proposal_response.status_code,
                        201,
                        proposal_response.text,
                    )
                    proposal = proposal_response.json()
                    accepted = client.post(
                        f"/economy/unlock-proposals/{proposal['id']}/respond",
                        json={
                            'request_id': f'hardware-stage-{stage}-accept',
                            'robot_id': 'robot-b',
                            'accepted': True,
                        },
                    )
                    self.assertEqual(accepted.status_code, 200, accepted.text)
                    self.assertEqual(accepted.json()['status'], 'COMPLETED')

                def assign_and_arrive(request_id, action, location, parameters):
                    response = client.post('/tasks', json={
                        'request_id': request_id,
                        'robot_id': 'robot-a',
                        'action': action,
                        'location': location,
                        'parameters': parameters,
                    })
                    self.assertEqual(response.status_code, 202, response.text)
                    task = response.json()
                    arrival = {
                        'session_id': session_id,
                        'task_id': task['id'],
                        'location': location,
                    }
                    accepted = client.post(
                        '/robots/robot-a/arrived', json=arrival,
                    )
                    self.assertEqual(accepted.status_code, 200, accepted.text)
                    return task, arrival

                _, buy_arrival = assign_and_arrive(
                    'hardware-buy', 'BUY', 'market',
                    {'item': 'seeds', 'quantity': 1},
                )
                purchased = client.get('/robots/robot-a').json()
                self.assertEqual(purchased['game']['money'], 3)
                self.assertEqual(
                    purchased['game']['inventory']['seeds']['quantity'], 1,
                )
                client.post(
                    '/robots/robot-a/arrived', json=buy_arrival,
                ).raise_for_status()
                self.assertEqual(
                    client.get('/robots/robot-a').json()['game']['money'], 3,
                )

                assign_and_arrive(
                    'hardware-plant', 'PLANT', 'farm',
                    {'item': 'seeds', 'plot_id': 'plot-1'},
                )
                planted = client.get('/world').json()
                self.assertEqual(planted['farm']['plots'][0]['status'], 'GROWING')
                self.assertNotIn(
                    'seeds', planted['robots'][0]['game']['inventory'],
                )

                time.sleep(.02)
                app.state.simulator.tick()
                self.assertEqual(
                    client.get('/world').json()['farm']['plots'][0]['status'],
                    'READY',
                )

                assign_and_arrive(
                    'hardware-harvest', 'HARVEST', 'farm',
                    {'plot_id': 'plot-1'},
                )
                self.assertEqual(
                    client.get('/robots/robot-a').json()['task']['status'],
                    'ACTIVE',
                )
                for _ in range(10):
                    app.state.simulator.tick()
                harvested = client.get('/robots/robot-a').json()
                self.assertIsNone(harvested['task'])
                self.assertEqual(
                    harvested['game']['inventory']['wheat']['quantity'], 3,
                )

                _, sell_arrival = assign_and_arrive(
                    'hardware-sell', 'SELL', 'market',
                    {'item': 'wheat', 'quantity': 3},
                )
                sold = client.get('/robots/robot-a').json()
                self.assertEqual(sold['game']['money'], 39)
                self.assertNotIn('wheat', sold['game']['inventory'])
                client.post(
                    '/robots/robot-a/arrived', json=sell_arrival,
                ).raise_for_status()
                completed_world = client.get('/world').json()
                final_robot = completed_world['robots'][0]
                self.assertEqual(final_robot['game']['money'], 39)
                self.assertEqual(final_robot['physical']['pose'], original_pose)
                self.assertEqual(completed_world['game']['stage'], 3)
                self.assertEqual(completed_world['game']['status'], 'COMPLETED')
                self.assertEqual(completed_world['game']['goal']['current'], 47)
                self.assertEqual(
                    [task['status'] for task in client.get('/tasks').json()['tasks']],
                    ['COMPLETED', 'COMPLETED', 'COMPLETED', 'COMPLETED'],
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
