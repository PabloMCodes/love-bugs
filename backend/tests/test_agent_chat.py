import asyncio
from copy import deepcopy
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.agents.__main__ import demo_world
from app.agents.chat import AgentChat
from app.agents.orchestrator import AgentOrchestrator
from app.agents.planner import Decision, MockPlanner
from app.api.agent_chat import DiscussionRequest, DiscussionService
from app.config import AgentConfig
from app.main import create_app


class ChatTests(unittest.TestCase):
    def test_bounded_history_and_session_reset(self):
        chat = AgentChat()
        world = demo_world()
        decision = Decision(action='WAIT', reason='Planning', message='Can you cover the lake?')
        for _ in range(105):
            chat.publish(world, 'robot-a', decision, status='proposed')
        self.assertEqual(len(chat.snapshot()['messages']), 100)
        self.assertEqual(len(chat.context(world)['agent_messages']), 20)
        world['session_id'] = 'new-game'
        self.assertEqual(chat.context(world)['agent_messages'], [])

    def test_plant_message_keeps_seed_and_plot_parameters(self):
        chat = AgentChat()
        world = demo_world()
        decision = Decision(
            action='PLANT',
            location='farm',
            item='seeds',
            plot_id='plot-2',
            reason='Fill an empty plot',
            message='I will plant the next wheat crop.',
        )

        chat.publish(world, 'robot-a', decision, status='accepted')

        self.assertEqual(
            chat.snapshot()['messages'][0]['parameters'],
            {'item': 'seeds', 'plot_id': 'plot-2'},
        )

    def test_routes_and_websocket_replay(self):
        service = DiscussionService(AgentConfig(interval_seconds=.001))
        with TestClient(create_app(service)) as client:
            result = client.post('/agent-chat/round', json={'world': demo_world()})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(len(result.json()['messages']), 2)
            self.assertEqual(result.json()['mode'], 'discussion')
            with client.websocket_connect('/agent-chat/events') as socket:
                replay = socket.receive_json()
                self.assertEqual(replay['messages'], result.json()['messages'])
            self.assertEqual(client.get('/agent-chat').json()['messages'], replay['messages'])
            self.assertEqual(client.post('/agent-chat/round', json={'world': {}}).status_code, 422)
            self.assertEqual(client.post('/agent-chat/round', json={
                'world': demo_world(), 'provider': 'unknown',
            }).status_code, 422)


class DiscussionTests(unittest.IsolatedAsyncioTestCase):
    async def test_peer_message_delivery_without_executing_tasks(self):
        service = DiscussionService(AgentConfig(interval_seconds=.001))
        heard = []
        class ListeningPlanner(MockPlanner):
            async def decide(inner, world, robot_id):
                heard.append(deepcopy(world.get('agent_messages', [])))
                return await super().decide(world, robot_id)
        service.planners['mock'] = ListeningPlanner()
        world = demo_world()
        world['game']['status'] = 'READY'
        before = deepcopy(world)
        result = await service.discuss(DiscussionRequest(world=world))
        self.assertEqual(heard[0], [])
        self.assertEqual(heard[1][0]['robot_id'], 'robot-a')
        self.assertEqual(result['messages'][1]['robot_id'], 'robot-b')
        self.assertEqual(world, before)
        self.assertTrue(all(m['status'] == 'proposed' for m in result['messages']))

    async def test_frontend_inventory_prices_are_available_for_discussion(self):
        world = demo_world()
        world['market']['items'] = [{'id': 'seeds', 'name': 'Seeds', 'buy_price': 5, 'stock': None}]
        world['robots'][0]['game']['inventory'] = {'fish': {'name': 'Salmon', 'quantity': 2, 'sell_price': 18}}
        service = DiscussionService()
        result = await service.discuss(DiscussionRequest(world=world))
        self.assertIsNone(result['error'])
        self.assertEqual(result['messages'][0]['action'], 'SELL')
        self.assertEqual(
            result['messages'][0]['parameters'],
            {'item': 'fish', 'quantity': 2},
        )
        self.assertNotIn('sell_price', world['market']['items'][0])

    async def test_round_cooldown(self):
        service = DiscussionService()
        request = DiscussionRequest(world=demo_world())
        await service.discuss(request)
        with self.assertRaises(HTTPException) as error:
            await service.discuss(request)
        self.assertEqual(error.exception.status_code, 429)

    async def test_mid_round_messages_visible_and_concurrent_round_rejected(self):
        service = DiscussionService()
        second_started = asyncio.Event()
        finish = asyncio.Event()
        class SlowPlanner(MockPlanner):
            async def decide(inner, world, robot_id):
                if robot_id == 'robot-b':
                    second_started.set()
                    await finish.wait()
                return await super().decide(world, robot_id)
        service.planners['mock'] = SlowPlanner()
        request = DiscussionRequest(world=demo_world())
        task = asyncio.create_task(service.discuss(request))
        await second_started.wait()
        self.assertEqual(len(service.snapshot()['messages']), 1)
        self.assertTrue(service.snapshot()['running'])
        with self.assertRaises(HTTPException) as error:
            await service.discuss(request)
        self.assertEqual(error.exception.status_code, 409)
        finish.set()
        await task

    async def test_stopped_game_and_busy_robots_do_not_chat(self):
        service = DiscussionService()
        world = demo_world()
        world['game']['status'] = 'STOPPED'
        result = await service.discuss(DiscussionRequest(world=world))
        self.assertEqual(result['messages'], [])

    async def test_model_error_does_not_invent_message(self):
        service = DiscussionService()
        class BrokenPlanner:
            async def decide(inner, world, robot_id):
                raise ValueError('Invalid output')
        service.planners['mock'] = BrokenPlanner()
        result = await service.discuss(DiscussionRequest(world=demo_world()))
        self.assertIsNotNone(result['error'])
        self.assertFalse(result['running'])
        self.assertEqual(result['messages'], [])

    async def test_orchestrator_passes_accepted_peer_messages(self):
        world = demo_world()
        heard = []
        class ListeningPlanner(MockPlanner):
            async def decide(inner, snapshot, robot_id):
                heard.append(deepcopy(snapshot['agent_messages']))
                return await super().decide(snapshot, robot_id)
        async def submit(session_id, request):
            robot = next(r for r in world['robots'] if r['id'] == request['robot_id'])
            robot['task'] = request
            return True
        orchestrator = AgentOrchestrator(ListeningPlanner())
        await orchestrator.tick(lambda: world, submit)
        self.assertEqual(heard[1][0]['status'], 'accepted')
        self.assertEqual(heard[1][0]['robot_id'], 'robot-a')
