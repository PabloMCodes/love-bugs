import asyncio
from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.agents.__main__ import demo_world
from app.agents.orchestrator import AgentOrchestrator
from app.agents.planner import Decision, MockPlanner, validate_decision


class DecisionTests(unittest.TestCase):
    def test_invalid_actions_parameters_and_destinations(self):
        for values in (
            {'action': 'MOTORS'},
            {'action': 'BUY', 'location': 'market', 'item': 'crop', 'quantity': True},
            {'action': 'SELL', 'location': 'market', 'item': 'crop', 'quantity': 0},
            {'action': 'WAIT', 'location': 'farm'},
            {'action': 'HARVEST', 'location': 'farm', 'robot_id': 'robot-b'},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                Decision(reason='test', **values)
        with self.assertRaises(ValueError):
            validate_decision(demo_world(), 'robot-a', Decision(action='HARVEST', location='lake', reason='test'))

    def test_inventory_formats_and_trade_validation(self):
        world = demo_world()
        decision = Decision(action='SELL', location='market', item='crop', quantity=2, reason='Earn gold')
        for inventory in ({'crop': 2}, {'crop': {'quantity': 2, 'name': 'Wheat'}}):
            world['robots'][0]['game']['inventory'] = inventory
            validate_decision(world, 'robot-a', decision)
        with self.assertRaises(ValueError):
            validate_decision(world, 'robot-a', decision.model_copy(update={'quantity': 3}))
        item = world['market']['items'][0]
        item.update(buy_price=10, stock=1)
        buy = Decision(action='BUY', location='market', item='crop', quantity=1, reason='Buy')
        validate_decision(world, 'robot-a', buy)
        for updates in ({'stock': 0}, {'stock': 1, 'buy_price': 50}, {'buy_price': None}):
            item.update(updates)
            with self.assertRaises(ValueError):
                validate_decision(world, 'robot-a', buy)


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.world = demo_world()
        self.requests = []

    async def submit(self, session_id, request):
        self.assertEqual(session_id, self.world['session_id'])
        self.requests.append(request)
        robot = next(r for r in self.world['robots'] if r['id'] == request['robot_id'])
        robot['task'] = {**request, 'status': 'ASSIGNED'}
        return True

    async def test_separate_robots_see_teammate_assignment_and_no_duplicates(self):
        seen = []
        class Planner(MockPlanner):
            async def decide(inner, world, robot_id):
                seen.append(deepcopy(world))
                return await super().decide(world, robot_id)
        orchestrator = AgentOrchestrator(Planner())
        outcomes = await orchestrator.tick(lambda: self.world, self.submit)
        self.assertEqual([r['action'] for r in self.requests], ['HARVEST', 'FISH'])
        self.assertEqual([o.status for o in outcomes], ['accepted', 'accepted'])
        self.assertIsNotNone(seen[1]['robots'][0]['task'])
        self.assertEqual(await orchestrator.tick(lambda: self.world, self.submit), [])

    async def test_unavailable_robots_and_stopped_game_skip_model(self):
        class FailPlanner:
            async def decide(inner, *args):
                self.fail('Must not call model')
        orchestrator = AgentOrchestrator(FailPlanner())
        for field, value in [('online', False), ('blocked', True), ('stopped', True),
                             ('tracking', 'STALE'), ('pose', None)]:
            self.world = demo_world()
            for robot in self.world['robots']:
                robot['physical'][field] = value
            self.assertEqual(await orchestrator.tick(lambda: self.world, self.submit), [])
        self.world = demo_world()
        for status in ('READY', 'STOPPED', 'COMPLETED'):
            self.world['game']['status'] = status
            self.assertEqual(await orchestrator.tick(lambda: self.world, self.submit), [])

    async def test_stop_or_reset_during_model_call_discards_decision(self):
        for reset in (False, True):
            self.world = demo_world()
            class Planner(MockPlanner):
                async def decide(inner, world, robot_id):
                    if reset:
                        self.world['session_id'] = 'new-session'
                    else:
                        self.world['game']['status'] = 'STOPPED'
                    return await super().decide(world, robot_id)
            await AgentOrchestrator(Planner()).tick(lambda: self.world, self.submit)
            self.assertEqual(self.requests, [])

    async def test_wait_cooldown_and_failure_isolation(self):
        calls = []
        class Planner:
            async def decide(inner, world, robot_id):
                calls.append(robot_id)
                if robot_id == 'robot-a':
                    raise RuntimeError('rate limit')
                return Decision(action='WAIT', reason='Wait for teammate')
        orchestrator = AgentOrchestrator(Planner())
        result = await orchestrator.tick(lambda: self.world, self.submit)
        self.assertEqual([o.status for o in result], ['error', 'waiting'])
        self.assertEqual(await orchestrator.tick(lambda: self.world, self.submit), [])
        self.assertEqual(len(calls), 2)

    async def test_timeout_and_overlapping_ticks(self):
        entered = asyncio.Event()
        class SlowPlanner:
            async def decide(inner, world, robot_id):
                entered.set()
                await asyncio.sleep(10)
        orchestrator = AgentOrchestrator(SlowPlanner(), timeout=.02)
        task = asyncio.create_task(orchestrator.tick(lambda: self.world, self.submit))
        await entered.wait()
        self.assertEqual(await orchestrator.tick(lambda: self.world, self.submit), [])
        self.assertEqual([o.status for o in await task], ['error', 'error'])
        self.assertEqual(self.requests, [])

    async def test_uncertain_submission_blocks_retry(self):
        async def uncertain(session_id, request):
            raise TimeoutError('reply lost')
        orchestrator = AgentOrchestrator(MockPlanner(), interval=.001)
        result = await orchestrator.tick(lambda: self.world, uncertain)
        self.assertEqual([o.status for o in result], ['uncertain', 'uncertain'])
        await asyncio.sleep(.002)
        self.assertEqual(await orchestrator.tick(lambda: self.world, self.submit), [])
        self.assertIsNotNone(result[0].request['request_id'])


class GeminiAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_adk_instances_with_mocked_model_response(self):
        from app.agents.gemini import GeminiPlanner
        with patch.dict(os.environ, {'GOOGLE_API_KEY': 'test-only'}, clear=True):
            planner = GeminiPlanner('gemini-2.5-flash-lite')
            first = planner._runner('robot-a')
            second = planner._runner('robot-b')
            self.assertIsNot(first.agent, second.agent)
            self.assertIs(first.agent.output_schema, Decision)
            self.assertEqual(first.agent.tools, [])
            from google.adk.models.base_llm import BaseLlm
            from google.adk.models.llm_response import LlmResponse
            from google.genai import types
            captured = []
            class FakeModel(BaseLlm):
                async def generate_content_async(inner, llm_request, stream=False):
                    captured.append(llm_request)
                    yield LlmResponse(content=types.Content(role='model', parts=[types.Part(
                        text=json.dumps({'action': 'HARVEST', 'location': 'farm', 'reason': 'Earn gold'})
                    )]))
            first.agent.model = FakeModel(model='test-model')
            decision = await planner.decide(demo_world(), 'robot-a')
            self.assertEqual(len(captured), 1)
            self.assertIn('robot-a', captured[0].contents[-1].parts[0].text)
            self.assertEqual(decision.action, 'HARVEST')
            sessions = await planner.sessions.list_sessions(app_name='love_bugs', user_id='robot-a')
            self.assertEqual(sessions.sessions, [])

    def test_missing_key_clear_error(self):
        from app.agents.gemini import GeminiPlanner
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'GOOGLE_API_KEY'):
            GeminiPlanner('gemini-2.5-flash-lite')


if __name__ == '__main__':
    unittest.main()
