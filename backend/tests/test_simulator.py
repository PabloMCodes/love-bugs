import unittest

from app.schemas import Point, Pose, TaskRequest
from app.simulation.simulator import SimulationRunner, move_pose_toward
from app.state import WorldStore, default_world


class MovementTests(unittest.TestCase):
    def test_move_pose_toward_uses_fixed_steps_and_snaps_on_arrival(self):
        pose, arrived = move_pose_toward(
            Pose(x=0, y=0, heading=90),
            target=Point(x=3, y=4),
            step_distance=2,
        )
        self.assertFalse(arrived)
        self.assertAlmostEqual(pose.x, 1.2)
        self.assertAlmostEqual(pose.y, 1.6)
        self.assertAlmostEqual(pose.heading, 53.130102, places=5)

        pose, arrived = move_pose_toward(
            pose,
            target=Point(x=3, y=4),
            step_distance=10,
        )
        self.assertTrue(arrived)
        self.assertEqual((pose.x, pose.y), (3, 4))

    def test_invalid_step_distance_is_rejected(self):
        with self.assertRaises(ValueError):
            move_pose_toward(
                Pose(x=0, y=0, heading=0),
                target=Point(x=1, y=1),
                step_distance=0,
            )


class SimulationRunnerTests(unittest.TestCase):
    def test_move_task_navigates_and_completes(self):
        store = WorldStore()
        store.start_game()
        store.assign_move_task(TaskRequest(
            request_id='simulation-move-001',
            robot_id='robot-a',
            action='MOVE_TO',
            location='farm',
        ))
        simulator = SimulationRunner(store, step_distance=5)

        simulator.tick()
        moving = store.snapshot().robots[0]
        self.assertEqual(moving.task.status, 'NAVIGATING')
        self.assertIsNone(moving.game.location)
        self.assertNotEqual((moving.physical.pose.x, moving.physical.pose.y), (12, 30))

        for _ in range(10):
            simulator.tick()

        world = store.snapshot()
        billy = world.robots[0]
        self.assertIsNone(billy.task)
        self.assertEqual(billy.game.location, 'farm')
        self.assertEqual((billy.physical.pose.x, billy.physical.pose.y), (20, 50))
        self.assertEqual(world.events[-1].type, 'robot_arrived')

    def test_idle_tick_does_not_change_revision(self):
        store = WorldStore()
        revision = store.snapshot().revision

        SimulationRunner(store).tick()

        self.assertEqual(store.snapshot().revision, revision)

    def test_fishing_starts_at_lake_and_rewards_inventory_once(self):
        store = WorldStore()
        store.start_game()
        store.assign_task(TaskRequest(
            request_id='simulation-fish-001',
            robot_id='robot-a',
            action='FISH',
            location='lake',
        ))
        simulator = SimulationRunner(store, interval_seconds=.25)

        simulator.tick()
        started = store.snapshot().robots[0]
        self.assertEqual(started.task.status, 'ACTIVE')
        self.assertEqual(started.task.progress, 0)

        simulator.tick()
        self.assertAlmostEqual(store.snapshot().robots[0].task.progress, .1)

        for _ in range(9):
            simulator.tick()

        completed = store.snapshot()
        billy = completed.robots[0]
        self.assertIsNone(billy.task)
        self.assertEqual(billy.game.inventory['fish'].quantity, 3)
        self.assertEqual(completed.events[-2].type, 'inventory_updated')
        self.assertEqual(completed.events[-1].type, 'task_completed')

        simulator.tick()
        self.assertEqual(store.snapshot().robots[0].game.inventory['fish'].quantity, 3)

    def test_harvest_travels_to_farm_before_activity(self):
        store = WorldStore()
        store.start_game()
        store.assign_task(TaskRequest(
            request_id='simulation-harvest-001',
            robot_id='robot-b',
            action='HARVEST',
            location='farm',
        ))
        simulator = SimulationRunner(store, interval_seconds=.25, step_distance=100)

        simulator.tick()
        milo = store.snapshot().robots[1]
        self.assertEqual(milo.game.location, 'farm')
        self.assertEqual(milo.task.status, 'ACTIVE')

        for _ in range(10):
            simulator.tick()

        milo = store.snapshot().robots[1]
        self.assertIsNone(milo.task)
        self.assertEqual(milo.game.inventory['crop'].quantity, 6)

    def test_sell_executes_once_after_market_arrival(self):
        store = WorldStore()
        store.start_game()
        store.assign_task(TaskRequest(
            request_id='simulation-sell-001',
            robot_id='robot-b',
            action='SELL',
            location='market',
            parameters={'item': 'crop', 'quantity': 2},
        ))
        simulator = SimulationRunner(store)

        simulator.tick()
        completed = store.snapshot()
        milo = completed.robots[1]
        self.assertIsNone(milo.task)
        self.assertEqual(milo.game.inventory['crop'].quantity, 1)
        self.assertEqual(milo.game.money, 64)
        self.assertEqual(completed.game.goal.current, 104)
        self.assertEqual(completed.events[-1].type, 'task_completed')

        revision = completed.revision
        simulator.tick()
        self.assertEqual(store.snapshot().revision, revision)
        self.assertEqual(store.snapshot().robots[1].game.money, 64)

    def test_sale_completes_goal_and_cancels_other_work(self):
        world = default_world()
        world['game']['goal']['target'] = 100
        store = WorldStore(world)
        store.start_game()
        store.assign_task(TaskRequest(
            request_id='simulation-other-move',
            robot_id='robot-a',
            action='MOVE_TO',
            location='farm',
        ))
        store.assign_task(TaskRequest(
            request_id='simulation-winning-sale',
            robot_id='robot-b',
            action='SELL',
            location='market',
            parameters={'item': 'crop', 'quantity': 2},
        ))

        SimulationRunner(store, step_distance=1).tick()

        completed = store.snapshot()
        self.assertEqual(completed.game.status, 'COMPLETED')
        self.assertEqual(completed.game.goal.current, 104)
        self.assertIsNone(completed.robots[0].task)
        self.assertIsNone(completed.robots[1].task)
        self.assertIn('task_cancelled', [event.type for event in completed.events])
        self.assertEqual(completed.events[-1].type, 'game_completed')


if __name__ == '__main__':
    unittest.main()
