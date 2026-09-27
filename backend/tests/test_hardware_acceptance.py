from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import unittest
from unittest.mock import patch

from app.game.acceptance import (
    build_parser,
    evaluate_hardware_game,
    evaluate_hardware_preflight,
    format_report,
    monitor,
)
from app.state import default_world


def ready_hardware_world():
    world = default_world('hardware')
    for index, robot in enumerate(world['robots']):
        robot['physical'].update({
            'online': True,
            'pose': {'x': 50, 'y': 30, 'heading': index * 180},
            'pose_updated_at': datetime.now(timezone.utc),
            'tracking': 'TRACKED',
            'battery': .8,
            'blocked': False,
            'stopped': False,
        })
    return world


def completed_hardware_round():
    world = ready_hardware_world()
    world['game'].update({'status': 'COMPLETED', 'stage': 3})
    world['game']['goal'].update({'current': 225, 'target': 200})
    for unlock in world['economy']['unlocks']:
        unlock['unlocked'] = True
    now = datetime.now(timezone.utc)
    robot_ids = [robot['id'] for robot in world['robots']]
    world['economy']['unlock_proposals'] = [
        {
            'id': f'proposal-{stage}',
            'stage': stage,
            'proposer_id': 'robot-a',
            'contributions': {'robot-a': 1, 'robot-b': 1},
            'accepted_by': robot_ids,
            'status': 'COMPLETED',
            'created_at': now,
            'resolved_at': now,
        }
        for stage in (2, 3)
    ]
    tasks = [
        {
            'id': f'task-{index}',
            'robot_id': 'robot-a' if index < 2 else 'robot-b',
            'action': action,
            'status': 'COMPLETED',
        }
        for index, action in enumerate(('BUY', 'PLANT', 'HARVEST', 'SELL'))
    ]
    return world, tasks


class HardwareAcceptanceTests(unittest.TestCase):
    def test_preflight_explains_missing_hardware_input(self):
        world = default_world('hardware')

        report = evaluate_hardware_preflight(world)

        self.assertFalse(report.passed)
        self.assertEqual(
            report.pending_keys,
            ('robot_input:robot-a', 'robot_input:robot-b'),
        )
        rendered = format_report(report)
        self.assertIn('WAIT Hardware input preflight', rendered)
        self.assertIn('offline, awaiting tracked pose', rendered)

    def test_preflight_accepts_fresh_input_and_required_service_points(self):
        report = evaluate_hardware_preflight(ready_hardware_world())

        self.assertTrue(report.passed)
        self.assertEqual(report.pending_keys, ())

    def test_complete_hardware_game_requires_full_loop_and_both_robots(self):
        world, tasks = completed_hardware_round()

        report = evaluate_hardware_game(world, tasks)

        self.assertTrue(report.passed, format_report(report))

        tasks[-1]['status'] = 'FAILED'
        failed = evaluate_hardware_game(world, tasks)
        self.assertIn('required_actions', failed.pending_keys)
        self.assertIn('no_failed_tasks', failed.pending_keys)

    def test_simulation_mode_and_invalid_cli_timing_are_rejected(self):
        report = evaluate_hardware_preflight(default_world())
        self.assertIn('hardware_mode', report.pending_keys)

        parser = build_parser()
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(['--timeout', '0'])
            with self.assertRaises(SystemExit):
                parser.parse_args(['--poll-seconds', 'nan'])

    def test_monitor_reads_live_contract_and_exits_on_pass(self):
        world, tasks = completed_hardware_round()
        paths = []

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def get(self, path):
                paths.append(path)
                return Response(world if path == '/world' else {'tasks': tasks})

        args = Namespace(
            backend_url='http://test',
            timeout=1,
            poll_seconds=.01,
            preflight_only=False,
        )
        with patch('app.game.acceptance.httpx.Client', return_value=Client()):
            with redirect_stdout(StringIO()) as output:
                result = monitor(args)

        self.assertEqual(result, 0)
        self.assertEqual(paths, ['/world', '/tasks'])
        self.assertIn('PASS Hardware game-loop acceptance', output.getvalue())


if __name__ == '__main__':
    unittest.main()
