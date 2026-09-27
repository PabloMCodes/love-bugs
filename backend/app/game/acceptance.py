"""Read-only acceptance monitor for a live hardware-mode game backend."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
import sys
import time

import httpx


REQUIRED_LOCATIONS = frozenset({'homebase', 'farm', 'lake', 'market'})
REQUIRED_ACTIONS = frozenset({'BUY', 'PLANT', 'HARVEST', 'SELL'})


@dataclass(frozen=True)
class AcceptanceCheck:
    key: str
    label: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class AcceptanceReport:
    name: str
    checks: tuple[AcceptanceCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def pending_keys(self) -> tuple[str, ...]:
        return tuple(check.key for check in self.checks if not check.passed)


def _check(key: str, label: str, passed: bool, detail: str) -> AcceptanceCheck:
    return AcceptanceCheck(key, label, bool(passed), detail)


def evaluate_hardware_preflight(world: dict) -> AcceptanceReport:
    """Evaluate facts the backend can prove before physical motion is armed."""
    robots = world.get('robots', [])
    game = world.get('game', {})
    world_map = world.get('map', {})
    locations = world_map.get('locations', {})
    missing_locations = sorted(REQUIRED_LOCATIONS - set(locations))
    checks = [
        _check(
            'hardware_mode',
            'Hardware runtime selected',
            world.get('mode') == 'hardware',
            f"mode={world.get('mode', 'missing')}",
        ),
        _check(
            'robot_count',
            'At least two robots are present',
            len(robots) >= 2,
            f'{len(robots)} robot(s)',
        ),
        _check(
            'service_points',
            'Required service points are configured',
            not missing_locations,
            (
                'homebase, farm, lake, and market present'
                if not missing_locations
                else 'missing ' + ', '.join(missing_locations)
            ),
        ),
    ]

    require_unstopped = game.get('status') == 'RUNNING'
    for robot in robots:
        robot_id = robot.get('id', 'unknown')
        physical = robot.get('physical', {})
        issues = []
        if physical.get('online') is not True:
            issues.append('offline')
        if (
            physical.get('tracking') != 'TRACKED'
            or physical.get('pose') is None
        ):
            issues.append('awaiting tracked pose')
        if physical.get('blocked') is not False:
            issues.append('blocked')
        if require_unstopped and physical.get('stopped') is not False:
            issues.append('stopped')
        checks.append(_check(
            f'robot_input:{robot_id}',
            f'{robot_id} supplies usable input',
            not issues,
            'ready' if not issues else ', '.join(issues),
        ))

    return AcceptanceReport('Hardware input preflight', tuple(checks))


def evaluate_hardware_game(world: dict, tasks: list[dict]) -> AcceptanceReport:
    """Evaluate a complete authoritative crop/economy/victory hardware round."""
    preflight = evaluate_hardware_preflight(world)
    robots = world.get('robots', [])
    robot_ids = {robot.get('id') for robot in robots if robot.get('id')}
    game = world.get('game', {})
    goal = game.get('goal', {})
    economy = world.get('economy', {})
    completed_tasks = [task for task in tasks if task.get('status') == 'COMPLETED']
    completed_actions = {task.get('action') for task in completed_tasks}
    missing_actions = sorted(REQUIRED_ACTIONS - completed_actions)
    participating_robots = {
        task.get('robot_id') for task in completed_tasks if task.get('robot_id')
    }
    completed_proposals = {
        proposal.get('stage'): proposal
        for proposal in economy.get('unlock_proposals', [])
        if proposal.get('status') == 'COMPLETED'
    }
    cooperative_stages = all(
        stage in completed_proposals
        and robot_ids.issubset(set(completed_proposals[stage].get('accepted_by', [])))
        for stage in (2, 3)
    )
    unlocks = economy.get('unlocks', [])
    unlocked_stages = {
        rule.get('stage') for rule in unlocks if rule.get('unlocked') is True
    }
    failed_tasks = [task for task in tasks if task.get('status') == 'FAILED']

    checks = [
        *preflight.checks,
        _check(
            'required_actions',
            'Crop-market loop completed from reported arrivals',
            not missing_actions,
            (
                'BUY, PLANT, HARVEST, and SELL completed'
                if not missing_actions
                else 'missing ' + ', '.join(missing_actions)
            ),
        ),
        _check(
            'robot_participation',
            'Every robot completed authoritative work',
            bool(robot_ids) and robot_ids.issubset(participating_robots),
            (
                'participants=' + ', '.join(sorted(participating_robots))
                if participating_robots
                else 'no completed robot tasks'
            ),
        ),
        _check(
            'cooperative_stages',
            'Both paid stage unlocks completed cooperatively',
            cooperative_stages,
            (
                'Stages 2 and 3 accepted by every robot'
                if cooperative_stages
                else 'waiting for completed two-robot Stage 2 and Stage 3 proposals'
            ),
        ),
        _check(
            'stage_three',
            'Final farming stage is active',
            game.get('stage') == 3 and {2, 3}.issubset(unlocked_stages),
            f"stage={game.get('stage', 'missing')}",
        ),
        _check(
            'victory',
            'Authoritative goal completed',
            (
                game.get('status') == 'COMPLETED'
                and isinstance(goal.get('current'), (int, float))
                and isinstance(goal.get('target'), (int, float))
                and goal['current'] >= goal['target']
            ),
            (
                f"status={game.get('status', 'missing')}, "
                f"gold={goal.get('current', 'missing')}/{goal.get('target', 'missing')}"
            ),
        ),
        _check(
            'no_failed_tasks',
            'No task failed during the accepted round',
            not failed_tasks,
            (
                'none'
                if not failed_tasks
                else ', '.join(str(task.get('id', 'unknown')) for task in failed_tasks)
            ),
        ),
    ]
    return AcceptanceReport('Hardware game-loop acceptance', tuple(checks))


def format_report(report: AcceptanceReport) -> str:
    lines = [f"{'PASS' if report.passed else 'WAIT'} {report.name}"]
    for check in report.checks:
        lines.append(
            f"  {'PASS' if check.passed else 'WAIT'} {check.label}: {check.detail}"
        )
    return '\n'.join(lines)


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError('must be a positive finite number')
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            'Wait for a hardware backend to prove telemetry readiness or the '
            'complete authoritative Love Bugs demo loop.'
        ),
    )
    parser.add_argument(
        '--backend-url',
        default='http://127.0.0.1:8000',
        help='Backend HTTP base URL (default: %(default)s)',
    )
    parser.add_argument(
        '--timeout',
        type=_positive_float,
        default=180,
        help='Maximum seconds to wait (default: %(default)s)',
    )
    parser.add_argument(
        '--poll-seconds',
        type=_positive_float,
        default=.5,
        help='Polling interval in seconds (default: %(default)s)',
    )
    parser.add_argument(
        '--preflight-only',
        action='store_true',
        help='Stop after both robot inputs and required service points are ready.',
    )
    return parser


def monitor(args: argparse.Namespace) -> int:
    deadline = time.monotonic() + args.timeout
    last_state = None
    last_report = None
    last_error = None

    with httpx.Client(
        base_url=args.backend_url.rstrip('/'),
        timeout=min(5, args.poll_seconds * 2),
    ) as client:
        while time.monotonic() < deadline:
            try:
                world_response = client.get('/world')
                world_response.raise_for_status()
                world = world_response.json()
                if world.get('mode') != 'hardware':
                    print(format_report(evaluate_hardware_preflight(world)))
                    print('FAIL Start the backend with GAME_MODE=hardware.', file=sys.stderr)
                    return 1
                tasks = []
                if not args.preflight_only:
                    tasks_response = client.get('/tasks')
                    tasks_response.raise_for_status()
                    tasks = tasks_response.json()['tasks']
                report = (
                    evaluate_hardware_preflight(world)
                    if args.preflight_only
                    else evaluate_hardware_game(world, tasks)
                )
                state = (world.get('session_id'), report.pending_keys)
                if state != last_state:
                    print(format_report(report), flush=True)
                    last_state = state
                last_report = report
                last_error = None
                if report.passed:
                    return 0
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                message = f'{type(error).__name__}: {error}'
                if message != last_error:
                    print(f'WAIT Backend unavailable or returned invalid data: {message}', flush=True)
                    last_error = message
            time.sleep(args.poll_seconds)

    if last_report is not None:
        print(format_report(last_report))
    print(f'FAIL Acceptance timed out after {args.timeout:g} seconds.', file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    return monitor(build_parser().parse_args(argv))


if __name__ == '__main__':
    raise SystemExit(main())
