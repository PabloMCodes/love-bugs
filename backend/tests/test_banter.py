import asyncio
from copy import deepcopy
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.agents.__main__ import demo_world
from app.agents.banter import BanterCoordinator
from app.agents.chat import AgentChat
from app.agents.planner import Decision, MockPlanner


class BanterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 0
        self.world = demo_world()
        self.chat = AgentChat()
        self.chat.reset(self.world['session_id'])
        self.banter = BanterCoordinator(MockPlanner(), self.chat, clock=lambda: self.now)
        await self.banter.tick(self.world)

    async def asyncTearDown(self):
        await self.banter.close()

    async def finish_line(self):
        await self.banter.pending
        await self.banter.tick(self.world)

    async def test_busy_robots_share_two_lines_without_changing_tasks(self):
        for robot in self.world['robots']:
            robot['task'] = {'action': 'HARVEST', 'status': 'ACTIVE'}
        before = deepcopy(self.world)
        self.now = 11
        await self.banter.tick(self.world)
        self.assertIsNone(self.banter.pending)
        self.now = 12
        await self.banter.tick(self.world)
        await self.finish_line()
        self.assertEqual(len(self.chat.messages), 1)
        self.assertEqual(self.chat.messages[0]['kind'], 'banter')
        self.assertEqual(self.chat.messages[0]['status'], 'conversation')
        self.now = 15
        await self.banter.tick(self.world)
        self.assertIsNone(self.banter.pending)
        self.now = 16
        await self.banter.tick(self.world)
        await self.finish_line()
        self.assertEqual(len(self.chat.messages), 2)
        self.assertNotEqual(self.chat.messages[0]['robot_id'], self.chat.messages[1]['robot_id'])
        self.assertIn('Wheels', self.chat.messages[1]['text'])
        self.assertEqual(self.world, before)
        self.now = 46
        await self.banter.tick(self.world)
        self.assertIsNone(self.banter.pending)
        self.now = 47
        await self.banter.tick(self.world)
        await self.finish_line()
        self.assertEqual(self.chat.messages[2]['robot_id'], 'robot-b')

    async def test_coordination_cancels_reply(self):
        self.now = 12
        await self.banter.tick(self.world)
        await self.finish_line()
        self.chat.publish(self.world, 'robot-b', Decision(action='WAIT', reason='Coordinate',
                          message='I need you at the farm.'), status='waiting')
        self.now = 16
        await self.banter.tick(self.world)
        self.assertIsNone(self.banter.reply)
        self.assertIsNone(self.banter.pending)
        self.assertEqual(len(self.chat.messages), 2)

    async def test_slow_generation_does_not_block_and_is_cancelled_on_stop(self):
        started = asyncio.Event()
        class SlowPlanner:
            async def converse(inner, *args):
                started.set()
                await asyncio.Event().wait()
        self.banter.planner = SlowPlanner()
        self.now = 12
        await asyncio.wait_for(self.banter.tick(self.world), .1)
        await started.wait()
        self.world['game']['status'] = 'STOPPED'
        await self.banter.tick(self.world)
        self.assertIsNone(self.banter.pending)
        self.assertEqual(self.chat.messages, [])

    async def test_new_task_cancels_inflight_joke(self):
        self.now = 12
        await self.banter.tick(self.world)
        await self.banter.pending
        await self.banter.tick(self.world, task_activity=True)
        self.assertEqual(self.chat.messages, [])
        self.assertIsNone(self.banter.pending)

    async def test_reset_discards_old_result_and_waits_for_quiet(self):
        self.now = 12
        await self.banter.tick(self.world)
        await self.banter.pending
        self.world['session_id'] = 'new'
        self.chat.reset('new')
        await self.banter.tick(self.world)
        self.assertEqual(self.chat.messages, [])
        self.assertIsNone(self.banter.pending)

    async def test_failure_is_not_retried_every_tick(self):
        class BrokenPlanner:
            async def converse(inner, *args):
                raise RuntimeError('unavailable')
        self.banter.planner = BrokenPlanner()
        self.now = 12
        await self.banter.tick(self.world)
        with self.assertRaises(RuntimeError):
            await self.banter.pending
        await self.banter.tick(self.world)
        self.now = 13
        await self.banter.tick(self.world)
        self.assertIsNone(self.banter.pending)
        self.assertEqual(self.chat.messages, [])

    async def test_no_banter_on_completed_game_or_robot_problem(self):
        self.now = 12
        self.world['robots'][1]['physical']['blocked'] = True
        await self.banter.tick(self.world)
        self.assertIsNone(self.banter.pending)
        self.world['robots'][1]['physical']['blocked'] = False
        self.world['game']['status'] = 'COMPLETED'
        self.now = 50
        await self.banter.tick(self.world)
        self.assertIsNone(self.banter.pending)


class GeminiBanterTests(unittest.IsolatedAsyncioTestCase):
    async def test_social_generation_has_no_task_tools_and_receives_actual_opener(self):
        from app.agents.gemini import GeminiPlanner, SocialLine
        with patch.dict(os.environ, {'GOOGLE_API_KEY': 'test-only'}):
            planner = GeminiPlanner('gemini-3.5-flash-lite')
        with patch.object(planner, '_generate', new=AsyncMock(return_value=SocialLine(message='Good thing we have wheels.'))) as generate:
            response = await planner.converse(demo_world(), 'robot-b', 'Imagine having tired legs.', 0)
        runner, robot_id, payload, schema = generate.await_args.args
        self.assertEqual(payload['reply_to'], 'Imagine having tired legs.')
        self.assertEqual(robot_id, 'robot-b')
        self.assertEqual(runner.agent.tools, [])
        self.assertIs(schema, SocialLine)
        self.assertEqual(response, 'Good thing we have wheels.')


if __name__ == '__main__':
    unittest.main()
