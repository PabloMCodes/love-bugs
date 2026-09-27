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
from app.schemas import WorldSnapshot
from app.state import default_world


def demo_world():
    world = default_world()
    world['session_id'] = 'agent-demo'
    world['game']['status'] = 'RUNNING'
    return WorldSnapshot.model_validate(world).model_dump(mode='json')


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
