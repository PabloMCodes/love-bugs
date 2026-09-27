import unittest

from app.schemas import Point, Pose, TaskRequest
from app.simulation.simulator import SimulationRunner, move_pose_toward
from app.state import WorldStateError, WorldStore, default_world


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
        self.assertNotEqual((moving.physical.pose.x, moving.physical.pose.y), (50, 30))

        for _ in range(10):
            simulator.tick()

        world = store.snapshot()
        billy = world.robots[0]
        self.assertIsNone(billy.task)
        self.assertEqual(billy.game.location, 'farm')
        self.assertEqual((billy.physical.pose.x, billy.physical.pose.y), (20, 50))
        self.assertEqual(world.events[-2].type, 'robot_arrived')
        self.assertEqual(world.events[-1].type, 'task_completed')

    def test_idle_tick_does_not_change_revision(self):
        store = WorldStore()
        revision = store.snapshot().revision

        SimulationRunner(store).tick()

        self.assertEqual(store.snapshot().revision, revision)

    def test_return_home_navigates_and_completes_as_return_home(self):
        store = WorldStore()
        store.start_game()
        task = store.assign_task(TaskRequest(
            request_id='simulation-return-home',
            robot_id='robot-a',
            action='RETURN_HOME',
            location='homebase',
        ))

        SimulationRunner(store, step_distance=100).tick()

        world = store.snapshot()
        billy = world.robots[0]
        self.assertIsNone(billy.task)
        self.assertEqual(billy.game.location, 'homebase')
        self.assertEqual((billy.physical.pose.x, billy.physical.pose.y), (50, 30))
        self.assertEqual(world.events[-1].type, 'task_completed')
        self.assertEqual(world.events[-1].message, 'Wall-y returned home.')
        completed = store.task(task.id)
        self.assertEqual(completed.action, 'RETURN_HOME')
        self.assertEqual(completed.status, 'COMPLETED')

    def test_fishing_starts_at_lake_and_rewards_inventory_once(self):
        store = WorldStore()
        store.start_game()
        store.assign_task(TaskRequest(
            request_id='simulation-fish-001',
            robot_id='robot-a',
            action='FISH',
            location='lake',
        ))
        simulator = SimulationRunner(
            store,
            interval_seconds=.25,
            step_distance=100,
        )

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
        self.assertEqual(billy.game.inventory['fish'].quantity, 1)
        self.assertEqual(completed.events[-2].type, 'inventory_updated')
        self.assertEqual(completed.events[-1].type, 'task_completed')

        simulator.tick()
        self.assertEqual(store.snapshot().robots[0].game.inventory['fish'].quantity, 1)

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
        self.assertEqual(milo.game.inventory['crop'].quantity, 3)

    def test_sell_executes_once_after_market_arrival(self):
        world = default_world()
        world['robots'][1]['game']['inventory']['crop'] = {
            'name': 'Wheat',
            'quantity': 3,
            'sell_price': 12,
        }
        store = WorldStore(world)
        store.start_game()
        store.assign_task(TaskRequest(
            request_id='simulation-sell-001',
            robot_id='robot-b',
            action='SELL',
            location='market',
            parameters={'item': 'crop', 'quantity': 2},
        ))
        simulator = SimulationRunner(store, step_distance=100)

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
        world['robots'][1]['physical']['pose'] = {'x': 80, 'y': 25, 'heading': 180}
        world['robots'][1]['game']['location'] = 'market'
        world['robots'][1]['game']['inventory']['crop'] = {
            'name': 'Wheat',
            'quantity': 2,
            'sell_price': 12,
        }
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

    def test_clean_round_collects_sells_and_completes_shared_goal_once(self):
        store = WorldStore()
        initial = store.snapshot()
        self.assertEqual(initial.game.status, 'READY')
        self.assertEqual(initial.game.goal.current, 80)
        self.assertEqual(initial.game.goal.target, 200)
        self.assertTrue(all(robot.game.location == 'homebase' for robot in initial.robots))
        self.assertTrue(all(robot.game.inventory == {} for robot in initial.robots))

        store.start_game()
        simulator = SimulationRunner(
            store,
            interval_seconds=2.5,
            step_distance=100,
        )

        request_number = 0

        def collect(robot_id, action, location):
            nonlocal request_number
            request_number += 1
            store.assign_task(TaskRequest(
                request_id=f'clean-round-collect-{request_number}',
                robot_id=robot_id,
                action=action,
                location=location,
            ))
            simulator.tick()
            simulator.tick()

        for _ in range(2):
            collect('robot-a', 'HARVEST', 'farm')
        for _ in range(3):
            collect('robot-b', 'FISH', 'lake')

        collected = store.snapshot()
        self.assertEqual(collected.robots[0].game.inventory['crop'].quantity, 6)
        self.assertEqual(collected.robots[1].game.inventory['fish'].quantity, 3)
        self.assertEqual(collected.game.goal.current, 80)

        store.assign_task(TaskRequest(
            request_id='clean-round-sell-wheat',
            robot_id='robot-a',
            action='SELL',
            location='market',
            parameters={'item': 'crop', 'quantity': 6},
        ))
        simulator.tick()
        after_wheat = store.snapshot()
        self.assertEqual(after_wheat.game.status, 'RUNNING')
        self.assertEqual(after_wheat.game.goal.current, 152)
        self.assertNotIn('crop', after_wheat.robots[0].game.inventory)

        store.assign_task(TaskRequest(
            request_id='clean-round-sell-fish',
            robot_id='robot-b',
            action='SELL',
            location='market',
            parameters={'item': 'fish', 'quantity': 3},
        ))
        simulator.tick()
        completed = store.snapshot()
        self.assertEqual(completed.game.status, 'COMPLETED')
        self.assertEqual(completed.game.goal.current, 206)
        self.assertEqual(completed.robots[0].game.money, 112)
        self.assertEqual(completed.robots[1].game.money, 94)
        self.assertNotIn('fish', completed.robots[1].game.inventory)
        self.assertEqual(
            sum(event.type == 'game_completed' for event in completed.events),
            1,
        )

        revision = completed.revision
        simulator.tick()
        self.assertEqual(store.snapshot().revision, revision)
        with self.assertRaises(WorldStateError) as context:
            store.assign_task(TaskRequest(
                request_id='clean-round-after-completion',
                robot_id='robot-a',
                action='RETURN_HOME',
                location='homebase',
            ))
        self.assertEqual(context.exception.code, 'GAME_NOT_RUNNING')

    def test_buy_executes_once_and_updates_wallet_inventory_and_stock(self):
        store = WorldStore()
        store.start_game()
        store.assign_task(TaskRequest(
            request_id='simulation-buy-001',
            robot_id='robot-b',
            action='BUY',
            location='market',
            parameters={'item': 'pumpkin_seeds', 'quantity': 1},
        ))
        simulator = SimulationRunner(store, step_distance=100)

        simulator.tick()
        completed = store.snapshot()
        milo = completed.robots[1]
        seeds = milo.game.inventory['pumpkin_seeds']
        market_seeds = next(
            item for item in completed.market.items if item.id == 'pumpkin_seeds'
        )
        self.assertIsNone(milo.task)
        self.assertEqual(milo.game.money, 20)
        self.assertEqual(seeds.quantity, 1)
        self.assertIsNone(seeds.sell_price)
        self.assertIsNone(market_seeds.stock)
        self.assertEqual(completed.game.goal.current, 60)
        self.assertEqual(completed.events[-1].type, 'task_completed')

        revision = completed.revision
        simulator.tick()
        self.assertEqual(store.snapshot().revision, revision)

    def test_competing_purchase_rechecks_stock_at_execution(self):
        world = default_world()
        next(
            item for item in world['market']['items']
            if item['id'] == 'pumpkin_seeds'
        )['stock'] = 1
        store = WorldStore(world)
        store.start_game()
        for robot_id in ('robot-a', 'robot-b'):
            store.assign_task(TaskRequest(
                request_id=f'simulation-buy-{robot_id}',
                robot_id=robot_id,
                action='BUY',
                location='market',
                parameters={'item': 'pumpkin_seeds', 'quantity': 1},
            ))

        SimulationRunner(store, step_distance=100).tick()

        completed = store.snapshot()
        billy, milo = completed.robots
        market_seeds = next(
            item for item in completed.market.items if item.id == 'pumpkin_seeds'
        )
        self.assertEqual(billy.game.inventory['pumpkin_seeds'].quantity, 1)
        self.assertNotIn('pumpkin_seeds', milo.game.inventory)
        self.assertEqual(milo.game.money, 40)
        self.assertIsNone(billy.task)
        self.assertIsNone(milo.task)
        self.assertEqual(market_seeds.stock, 0)
        self.assertEqual(completed.events[-1].type, 'task_failed')
        self.assertEqual(completed.events[-1].data['code'], 'OUT_OF_STOCK')


if __name__ == '__main__':
    unittest.main()
