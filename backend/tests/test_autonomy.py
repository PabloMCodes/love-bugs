import asyncio
from datetime import datetime, timedelta, timezone
import unittest

from app.agents.orchestrator import AgentOrchestrator
from app.agents.planner import MockPlanner
from app.agents.runtime import AutonomyRunner
from app.schemas import TaskRequest
from app.simulation.simulator import SimulationRunner
from app.state import WorldStateError, WorldStore, default_world


class AutonomyRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_autonomy_completes_round_without_browser(self):
        world = default_world()
        planted_at = datetime.now(timezone.utc) - timedelta(seconds=9)
        world['farm']['plots'][0].update({
            'status': 'READY',
            'crop_id': 'wheat',
            'planted_by': 'robot-a',
            'planted_at': planted_at,
            'ready_at': planted_at + timedelta(seconds=8),
        })
        store = WorldStore(world)
        store.start_game()
        orchestrator = AgentOrchestrator(
            MockPlanner(),
            interval=.001,
            timeout=1,
        )
        runner = AutonomyRunner(
            store,
            orchestrator,
            poll_interval_seconds=.001,
        )
        simulator = SimulationRunner(
            store,
            interval_seconds=2.5,
            step_distance=100,
        )

        for _ in range(12):
            await runner.tick()
            simulator.tick()
            simulator.tick()
            if store.snapshot().game.status == 'COMPLETED':
                break
            await asyncio.sleep(.002)
        else:
            self.fail('Mock autonomy did not complete the repair-fund round')

        world = store.snapshot()
        actions = [task.action for task in store.tasks()]
        self.assertEqual(world.game.status, 'COMPLETED')
        self.assertGreaterEqual(world.game.goal.current, world.game.goal.target)
        self.assertIn('HARVEST', actions)
        self.assertIn('FISH', actions)
        self.assertIn('SELL', actions)
        self.assertTrue(all(robot.task is None for robot in world.robots))
        self.assertIn('agent_decision', [event.type for event in world.events])
        self.assertTrue(
            all(
                message['status'] == 'accepted'
                for message in orchestrator.chat.snapshot()['messages']
            )
        )

    async def test_runner_rejects_old_session_without_assigning_task(self):
        store = WorldStore()
        store.start_game()
        runner = AutonomyRunner(
            store,
            AgentOrchestrator(MockPlanner()),
        )
        request = TaskRequest(
            request_id='stale-autonomous-task',
            robot_id='robot-a',
            action='HARVEST',
            location='farm',
        ).model_dump(mode='json')

        accepted = await runner.submit_task('old-session', request)

        self.assertFalse(accepted)
        self.assertEqual(store.tasks(), [])
        self.assertTrue(all(robot.task is None for robot in store.snapshot().robots))

    def test_store_session_check_is_atomic_with_task_assignment(self):
        store = WorldStore()
        store.start_game()
        request = TaskRequest(
            request_id='session-checked-task',
            robot_id='robot-a',
            action='HARVEST',
            location='farm',
        )

        with self.assertRaises(WorldStateError) as context:
            store.assign_task_for_session('old-session', request)

        self.assertEqual(context.exception.code, 'SESSION_MISMATCH')
        self.assertEqual(store.tasks(), [])


if __name__ == '__main__':
    unittest.main()
