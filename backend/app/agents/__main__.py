"""One planning round with an in-memory task sink; no robot or backend I/O."""

import argparse
import asyncio
from copy import deepcopy
import json
import logging
from pathlib import Path

from app.agents.orchestrator import AgentOrchestrator
from app.agents.planner import Decision, MockPlanner, validate_decision
from app.config import AgentConfig


def demo_world():
    return {
        'session_id': 'agent-demo', 'revision': 1, 'mode': 'simulation',
        'game': {'status': 'RUNNING', 'goal': {'type': 'earn_gold', 'current': 80, 'target': 500}},
        'map': {'width': 100, 'height': 100, 'locations': {
            'homebase': {'x': 50, 'y': 50}, 'farm': {'x': 20, 'y': 30},
            'lake': {'x': 70, 'y': 80}, 'market': {'x': 80, 'y': 40}}},
        'robots': [{'id': robot_id, 'name': name,
                    'physical': {'online': True, 'stopped': False, 'blocked': False,
                                 'tracking': 'TRACKED', 'pose': {'x': 50, 'y': 50, 'heading': 0}},
                    'game': {'location': 'homebase', 'money': 40, 'inventory': {}}, 'task': None}
                   for robot_id, name in [('robot-a', 'Wall-y'), ('robot-b', 'Eve')]],
        'market': {'items': [{'id': 'crop', 'name': 'Wheat', 'buy_price': None, 'sell_price': 12, 'stock': None},
                             {'id': 'fish', 'name': 'Fish', 'buy_price': None, 'sell_price': 18, 'stock': None}]},
    }


async def run(args):
    config = AgentConfig.from_env()
    world = json.loads(args.world.read_text()) if args.world else demo_world()
    if args.provider == 'gemini':
        from app.agents.gemini import GeminiPlanner
        planner = GeminiPlanner(config.model)
    else:
        planner = MockPlanner()
    orchestrator = AgentOrchestrator(planner, interval=config.interval_seconds,
                                    timeout=config.timeout_seconds)

    async def submit(session_id, request):
        # Demo acceptance only. Production must use the shared game task service.
        if world['session_id'] != session_id:
            return False
        validate_decision(world, request['robot_id'], Decision(
            action=request['action'], location=request['location'], reason=request['reason'],
            **request['parameters']))
        robot = next(r for r in world['robots'] if r['id'] == request['robot_id'])
        robot['task'] = {**deepcopy(request), 'id': request['request_id'], 'status': 'ASSIGNED',
                         'progress': 0, 'error': None}
        world['revision'] += 1
        return True

    outcomes = await orchestrator.tick(lambda: world, submit)
    print(json.dumps({'mode': 'dry_run', 'provider': args.provider,
                      'messages': orchestrator.chat.snapshot()['messages'],
                      'outcomes': [outcome.to_dict() for outcome in outcomes]}, indent=2))
    return int(any(outcome.status in ('error', 'uncertain') for outcome in outcomes))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=('mock', 'gemini'), default='mock')
    parser.add_argument('--world', type=Path, help='Optional JSON world snapshot; never modified on disk')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        return asyncio.run(run(args))
    except (ValueError, OSError, KeyError) as error:
        logging.error('%s', error)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
