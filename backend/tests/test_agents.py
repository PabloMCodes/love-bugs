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
from app.state import default_world


class DecisionTests(unittest.TestCase):
    def test_invalid_actions_parameters_and_destinations(self):
        for values in (
            {'action': 'MOTORS'},
            {'action': 'BUY', 'location': 'market', 'item': 'crop', 'quantity': True},
            {'action': 'SELL', 'location': 'market', 'item': 'crop', 'quantity': 0},
            {'action': 'WAIT', 'location': 'farm'},
            {'action': 'HARVEST', 'location': 'farm', 'robot_id': 'robot-b'},
            {'action': 'PLANT', 'location': 'farm', 'item': 'seeds'},
            {
                'action': 'PLANT',
                'location': 'farm',
                'item': 'seeds',
                'plot_id': 'plot-1',
                'quantity': 1,
            },
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                Decision(reason='test', **values)
        with self.assertRaises(ValueError):
            validate_decision(
                demo_world(),
                'robot-a',
                Decision(
                    action='HARVEST',
                    location='lake',
                    plot_id='plot-1',
                    reason='test',
                ),
            )

    def test_plant_validation_uses_owned_seed_and_empty_plot(self):
        world = default_world()
        world['game']['status'] = 'RUNNING'
        decision = Decision(
            action='PLANT',
            location='farm',
            item='seeds',
            plot_id='plot-1',
            reason='Start the crop queue',
        )

        with self.assertRaisesRegex(ValueError, 'not in this robot inventory'):
            validate_decision(world, 'robot-a', decision)

        world['robots'][0]['game']['inventory']['seeds'] = {
            'name': 'Wheat Seeds',
            'quantity': 1,
            'sell_price': None,
        }
        validate_decision(world, 'robot-a', decision)

        world['farm']['plots'][0]['status'] = 'GROWING'
        with self.assertRaisesRegex(ValueError, 'not empty'):
            validate_decision(world, 'robot-a', decision)

        world['farm']['plots'][0]['status'] = 'EMPTY'
        world['robots'][1]['task'] = {
            'action': 'PLANT',
            'parameters': {'item': 'seeds', 'plot_id': 'plot-1'},
        }
        with self.assertRaisesRegex(ValueError, 'already claimed'):
            validate_decision(world, 'robot-a', decision)

    def test_inventory_formats_and_trade_validation(self):
        world = demo_world()
        world['market']['items'] = [{
            'id': 'crop',
            'name': 'Wheat',
            'buy_price': 10,
            'sell_price': 12,
            'stock': 1,
            'required_stage': 1,
        }]
        decision = Decision(action='SELL', location='market', item='crop', quantity=2, reason='Earn gold')
        for inventory in (
            {'crop': 2},
            {'crop': {'quantity': 2, 'name': 'Wheat', 'sell_price': 12}},
        ):
            world['robots'][0]['game']['inventory'] = inventory
            validate_decision(world, 'robot-a', decision)
        with self.assertRaises(ValueError):
            validate_decision(world, 'robot-a', decision.model_copy(update={'quantity': 3}))
        item = world['market']['items'][0]
        item.update(buy_price=10, stock=1, required_stage=2)
        buy = Decision(action='BUY', location='market', item='crop', quantity=1, reason='Buy')
        with self.assertRaisesRegex(ValueError, 'locked'):
            validate_decision(world, 'robot-a', buy)
        item['required_stage'] = 1
        validate_decision(world, 'robot-a', buy)
        for updates in ({'stock': 0}, {'stock': 1, 'buy_price': 50}, {'buy_price': None}):
            item.update(updates)
            with self.assertRaises(ValueError):
                validate_decision(world, 'robot-a', buy)

    def test_sell_validation_uses_selected_robots_inventory(self):
        world = demo_world()
        world['market']['items'] = [
            {
                'id': 'seeds',
                'name': 'Wheat Seeds',
                'buy_price': 5,
                'sell_price': None,
                'stock': None,
            },
        ]
        world['robots'][0]['game']['inventory'] = {
            'crop': {'name': 'Wheat', 'quantity': 2, 'sell_price': 12},
        }
        decision = Decision(
            action='SELL',
            location='market',
            item='crop',
            quantity=2,
            reason='Earn gold',
        )

        validate_decision(world, 'robot-a', decision)

        with self.assertRaisesRegex(ValueError, 'Insufficient inventory'):
            validate_decision(
                world,
                'robot-a',
                decision.model_copy(update={'quantity': 3}),
            )

        world['robots'][0]['game']['inventory']['crop']['sell_price'] = None
        with self.assertRaisesRegex(ValueError, 'unavailable for sale'):
            validate_decision(world, 'robot-a', decision)

        world['robots'][0]['game']['inventory'] = {}
        world['robots'][1]['game']['inventory'] = {
            'crop': {'name': 'Wheat', 'quantity': 2, 'sell_price': 12},
        }
        with self.assertRaisesRegex(ValueError, 'Insufficient inventory'):
            validate_decision(world, 'robot-a', decision)

    def test_economy_decisions_require_their_own_parameters(self):
        for values in (
            {'action': 'PROPOSE_UNLOCK', 'stage': 2},
            {'action': 'RESPOND_UNLOCK', 'proposal_id': 'proposal-1'},
            {'action': 'TRANSFER_MONEY', 'recipient_id': 'robot-b'},
            {'action': 'REQUEST_MONEY', 'amount': 5},
            {'action': 'RESPOND_MONEY', 'money_request_id': 'request-1'},
            {
                'action': 'TRANSFER_MONEY',
                'recipient_id': 'robot-b',
                'amount': 5,
                'location': 'market',
            },
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                Decision(reason='Coordinate the economy', **values)


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
        self.assertEqual([r['action'] for r in self.requests], ['BUY', 'BUY'])
        self.assertEqual([o.status for o in outcomes], ['accepted', 'accepted'])
        self.assertIsNotNone(seen[1]['robots'][0]['task'])
        self.assertEqual(await orchestrator.tick(lambda: self.world, self.submit), [])

    async def test_mock_planner_sells_inventory_absent_from_market_catalog(self):
        self.world['market']['items'] = [
            {
                'id': 'seeds',
                'name': 'Wheat Seeds',
                'buy_price': 5,
                'sell_price': None,
                'stock': None,
            },
        ]
        self.world['robots'][0]['game']['inventory'] = {
            'seeds': {'name': 'Wheat Seeds', 'quantity': 1, 'sell_price': None},
            'crop': {'name': 'Wheat', 'quantity': 3, 'sell_price': 12},
        }

        outcomes = await AgentOrchestrator(MockPlanner()).tick(
            lambda: self.world,
            self.submit,
        )

        self.assertEqual([request['action'] for request in self.requests], ['SELL', 'BUY'])
        self.assertEqual(
            self.requests[0]['parameters'],
            {'item': 'crop', 'quantity': 3},
        )
        self.assertEqual([outcome.status for outcome in outcomes], ['accepted', 'accepted'])

    async def test_mock_planner_claims_ready_plot(self):
        self.world['farm']['plots'] = [{
            'id': 'plot-1',
            'status': 'READY',
            'crop_id': 'wheat',
            'planted_by': 'robot-a',
            'planted_at': '2026-09-27T12:00:00Z',
            'ready_at': '2026-09-27T12:00:08Z',
        }]

        outcomes = await AgentOrchestrator(MockPlanner()).tick(
            lambda: self.world,
            self.submit,
        )

        self.assertEqual(self.requests[0]['action'], 'HARVEST')
        self.assertEqual(self.requests[0]['parameters'], {'plot_id': 'plot-1'})
        self.assertEqual(outcomes[0].status, 'accepted')

    async def test_mock_planner_buys_seeds_for_empty_capacity(self):
        self.world = default_world()
        self.world['game']['status'] = 'RUNNING'

        outcomes = await AgentOrchestrator(MockPlanner()).tick(
            lambda: self.world,
            self.submit,
        )

        self.assertEqual(
            [request['action'] for request in self.requests],
            ['BUY', 'BUY'],
        )
        self.assertTrue(
            all(
                request['parameters'] == {'item': 'seeds', 'quantity': 1}
                for request in self.requests
            )
        )
        self.assertEqual([outcome.status for outcome in outcomes], ['accepted', 'accepted'])

    async def test_mock_planner_prefers_best_unlocked_crop_return(self):
        for stage, expected_seed in (
            (1, 'seeds'),
            (2, 'carrot_seeds'),
            (3, 'pumpkin_seeds'),
        ):
            with self.subTest(stage=stage):
                world = default_world()
                world['game']['status'] = 'RUNNING'
                world['game']['stage'] = stage

                decision = await MockPlanner().decide(world, 'robot-a')

                self.assertEqual(decision.action, 'BUY')
                self.assertEqual(decision.item, expected_seed)
                self.assertEqual(decision.quantity, 1)

    async def test_mock_planner_proposes_and_accepts_stage_unlock(self):
        self.world = default_world()
        self.world['game']['status'] = 'RUNNING'
        self.world['robots'][0]['game']['money'] = 60
        self.world['robots'][1]['game']['money'] = 50
        self.world['game']['goal']['current'] = 110

        proposed = await MockPlanner().decide(self.world, 'robot-a')

        self.assertEqual(proposed.action, 'PROPOSE_UNLOCK')
        self.assertEqual(proposed.stage, 2)
        self.assertEqual(sum(proposed.contributions.values()), 30)
        self.world['economy']['unlock_proposals'].append({
            'id': 'proposal-1',
            'stage': 2,
            'proposer_id': 'robot-a',
            'contributions': proposed.contributions,
            'accepted_by': ['robot-a'],
            'status': 'PENDING',
            'created_at': '2026-09-27T12:00:00Z',
            'resolved_at': None,
        })

        response = await MockPlanner().decide(self.world, 'robot-b')

        self.assertEqual(response.action, 'RESPOND_UNLOCK')
        self.assertEqual(response.proposal_id, 'proposal-1')
        self.assertTrue(response.accepted)

    async def test_mock_planner_claims_distinct_empty_plots(self):
        self.world = default_world()
        self.world['game']['status'] = 'RUNNING'
        for robot in self.world['robots']:
            robot['game']['inventory']['seeds'] = {
                'name': 'Wheat Seeds',
                'quantity': 1,
                'sell_price': None,
            }

        await AgentOrchestrator(MockPlanner()).tick(
            lambda: self.world,
            self.submit,
        )

        self.assertEqual(
            [request['action'] for request in self.requests],
            ['PLANT', 'PLANT'],
        )
        self.assertEqual(
            [request['parameters']['plot_id'] for request in self.requests],
            ['plot-1', 'plot-2'],
        )
        self.assertTrue(
            all(request['parameters']['item'] == 'seeds' for request in self.requests)
        )

    async def test_pending_seed_purchase_prevents_excess_buying(self):
        self.world = default_world()
        self.world['game']['status'] = 'RUNNING'
        self.world['farm']['plots'] = [self.world['farm']['plots'][0]]

        await AgentOrchestrator(MockPlanner()).tick(
            lambda: self.world,
            self.submit,
        )

        self.assertEqual(
            [request['action'] for request in self.requests],
            ['BUY', 'FISH'],
        )

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

    async def test_api_error_reports_status_and_redacts_key(self):
        from google.genai.errors import ClientError
        secret = 'test-private-api-key'
        class RejectedPlanner:
            async def decide(inner, world, robot_id):
                raise ClientError(403, {'error': {
                    'status': 'PERMISSION_DENIED',
                    'message': f'Access denied for {secret}; https://example.test/?key=other-secret',
                }})
        with patch.dict(os.environ, {'GOOGLE_API_KEY': secret}):
            with self.assertLogs('app.agents.orchestrator', level='WARNING') as logs:
                result = await AgentOrchestrator(RejectedPlanner()).tick(lambda: self.world, self.submit)
        output = json.dumps([outcome.to_dict() for outcome in result]) + str(logs.output)
        self.assertIn('403 PERMISSION_DENIED', output)
        self.assertNotIn(secret, output)
        self.assertNotIn('other-secret', output)
        self.assertIn('[REDACTED]', output)
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
    def test_decision_schema_converts_for_gemini(self):
        # Exercise the SDK conversion that runs before any HTTP request. ADK's
        # fake-model tests do not catch unsupported JSON Schema constraints.
        from google.genai import Client, _transformers
        from app.agents.gemini import GeminiDecisionSchema
        with Client(api_key='test-only') as client:
            schema = _transformers.t_schema(client._api_client, GeminiDecisionSchema)
        self.assertEqual(schema.properties['quantity'].minimum, 1)
        self.assertTrue(schema.properties['quantity'].nullable)
        wire_schema = schema.model_dump(mode='json', by_alias=True, exclude_none=True)
        self.assertNotIn('additionalProperties', wire_schema)
        self.assertNotIn('additional_properties', wire_schema)
        with self.assertRaises(ValidationError):
            Decision.model_validate_json(json.dumps({
                'action': 'HARVEST', 'location': 'farm', 'plot_id': 'plot-1',
                'reason': 'Earn gold',
                'motor_speed': 1,
            }))


    async def test_real_adk_instances_with_mocked_model_response(self):
        from app.agents.gemini import GeminiPlanner, GeminiDecisionSchema
        with patch.dict(os.environ, {'GOOGLE_API_KEY': 'test-only'}, clear=True):
            planner = GeminiPlanner('gemini-3.5-flash-lite')
            first = planner._runner('robot-a')
            second = planner._runner('robot-b')
            self.assertIsNot(first.agent, second.agent)
            self.assertIs(first.agent.output_schema, GeminiDecisionSchema)
            self.assertEqual(first.agent.tools, [])
            from google.adk.models.base_llm import BaseLlm
            from google.adk.models.llm_response import LlmResponse
            from google.genai import types
            captured = []
            class FakeModel(BaseLlm):
                async def generate_content_async(inner, llm_request, stream=False):
                    captured.append(llm_request)
                    yield LlmResponse(content=types.Content(role='model', parts=[types.Part(
                        text=json.dumps({
                            'action': 'HARVEST',
                            'location': 'farm',
                            'plot_id': 'plot-1',
                            'reason': 'Earn gold',
                        })
                    )]))
            first.agent.model = FakeModel(model='test-model')
            world = demo_world()
            world['agent_messages'] = [{'robot_id': 'robot-b', 'text': 'Can you cover the farm?'}]
            decision = await planner.decide(world, 'robot-a')
            self.assertEqual(len(captured), 1)
            self.assertIn('robot-a', captured[0].contents[-1].parts[0].text)
            self.assertIn('Can you cover the farm?', captured[0].contents[-1].parts[0].text)
            payload = json.loads(captured[0].contents[-1].parts[0].text)
            self.assertEqual(payload['conversation_focus']['peer_messages_since_your_last_public_message'][0]['text'],
                             'Can you cover the farm?')
            self.assertEqual(decision.action, 'HARVEST')
            sessions = await planner.sessions.list_sessions(app_name='love_bugs', user_id='robot-a')
            self.assertEqual(sessions.sessions, [])

    def test_missing_key_clear_error(self):
        from app.agents.gemini import GeminiPlanner, GeminiDecisionSchema
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'GOOGLE_API_KEY'):
            GeminiPlanner('gemini-3.5-flash-lite')


if __name__ == '__main__':
    unittest.main()
