from datetime import datetime, timedelta, timezone
import unittest

from app.schemas import (
    EconomyResponseRequest,
    Point,
    Pose,
    StageUnlockProposalRequest,
    TaskRequest,
)
from app.simulation.simulator import SimulationRunner, move_pose_toward
from app.state import WorldStateError, WorldStore, default_world


def ready_wheat_plot(world: dict, plot_index: int = 0) -> str:
    planted_at = datetime.now(timezone.utc) - timedelta(seconds=9)
    plot = world['farm']['plots'][plot_index]
    plot.update({
        'status': 'READY',
        'crop_id': 'wheat',
        'planted_by': 'robot-a',
        'planted_at': planted_at,
        'ready_at': planted_at + timedelta(seconds=8),
    })
    return plot['id']


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
        task = store.assign_task(TaskRequest(
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

        duration = task.parameters['duration_seconds']
        catch = task.parameters['catch']
        store.advance_activities(duration / 10)
        self.assertAlmostEqual(store.snapshot().robots[0].task.progress, .1)
        store.advance_activities(duration * .9)

        completed = store.snapshot()
        billy = completed.robots[0]
        self.assertIsNone(billy.task)
        self.assertEqual(billy.game.inventory[catch['item_id']].quantity, 1)
        self.assertEqual(completed.events[-2].type, 'fish_caught')
        self.assertEqual(completed.events[-1].type, 'task_completed')

        simulator.tick()
        self.assertEqual(
            store.snapshot().robots[0].game.inventory[catch['item_id']].quantity,
            1,
        )

    def test_harvest_travels_to_farm_before_activity(self):
        world = default_world()
        plot_id = ready_wheat_plot(world)
        store = WorldStore(world)
        store.start_game()
        request = TaskRequest(
            request_id='simulation-harvest-001',
            robot_id='robot-b',
            action='HARVEST',
            location='farm',
            parameters={'plot_id': plot_id},
        )
        task = store.assign_task(request)
        simulator = SimulationRunner(store, interval_seconds=.25, step_distance=100)

        simulator.tick()
        milo = store.snapshot().robots[1]
        self.assertEqual(milo.game.location, 'farm')
        self.assertEqual(milo.task.status, 'ACTIVE')

        for _ in range(10):
            simulator.tick()

        milo = store.snapshot().robots[1]
        self.assertIsNone(milo.task)
        self.assertEqual(milo.game.inventory['wheat'].quantity, 3)
        self.assertEqual(store.snapshot().farm.plots[0].status, 'EMPTY')

        revision = store.snapshot().revision
        retried = store.assign_task(request)
        simulator.tick()
        self.assertEqual(retried.id, task.id)
        self.assertEqual(retried.status, 'COMPLETED')
        self.assertEqual(store.snapshot().revision, revision)
        self.assertEqual(store.snapshot().robots[1].game.inventory['wheat'].quantity, 3)

    def test_competing_harvest_rechecks_plot_before_granting_crop(self):
        world = default_world()
        plot_id = ready_wheat_plot(world)
        store = WorldStore(world)
        store.start_game()
        for robot_id in ('robot-a', 'robot-b'):
            store.assign_task(TaskRequest(
                request_id=f'simulation-harvest-{robot_id}',
                robot_id=robot_id,
                action='HARVEST',
                location='farm',
                parameters={'plot_id': plot_id},
            ))
        simulator = SimulationRunner(
            store,
            interval_seconds=2.5,
            step_distance=100,
        )

        simulator.tick()
        simulator.tick()

        harvested = store.snapshot()
        self.assertEqual(harvested.robots[0].game.inventory['wheat'].quantity, 3)
        self.assertNotIn('wheat', harvested.robots[1].game.inventory)
        self.assertEqual(harvested.farm.plots[0].status, 'EMPTY')
        self.assertEqual(harvested.events[-1].type, 'task_failed')
        self.assertEqual(harvested.events[-1].data['code'], 'PLOT_NOT_READY')

    def test_cancelled_harvest_keeps_ready_plot_and_grants_no_crop(self):
        world = default_world()
        plot_id = ready_wheat_plot(world)
        store = WorldStore(world)
        store.start_game()
        store.assign_task(TaskRequest(
            request_id='simulation-harvest-cancelled',
            robot_id='robot-a',
            action='HARVEST',
            location='farm',
            parameters={'plot_id': plot_id},
        ))

        store.stop_game()

        stopped = store.snapshot()
        self.assertEqual(stopped.farm.plots[0].status, 'READY')
        self.assertNotIn('wheat', stopped.robots[0].game.inventory)

    def test_plant_consumes_one_seed_and_populates_plot_once(self):
        world = default_world()
        world['robots'][0]['game']['inventory']['seeds'] = {
            'name': 'Wheat Seeds',
            'quantity': 2,
            'sell_price': None,
        }
        store = WorldStore(world)
        store.start_game()
        request = TaskRequest(
            request_id='simulation-plant-001',
            robot_id='robot-a',
            action='PLANT',
            location='farm',
            parameters={'item': 'seeds', 'plot_id': 'plot-1'},
        )
        task = store.assign_task(request)
        simulator = SimulationRunner(store, step_distance=100)

        simulator.tick()

        planted = store.snapshot()
        robot = planted.robots[0]
        plot = planted.farm.plots[0]
        self.assertIsNone(robot.task)
        self.assertEqual(robot.game.inventory['seeds'].quantity, 1)
        self.assertEqual(plot.status, 'GROWING')
        self.assertEqual(plot.crop_id, 'wheat')
        self.assertEqual(plot.planted_by, 'robot-a')
        self.assertEqual(plot.ready_at - plot.planted_at, timedelta(seconds=8))
        self.assertEqual(
            [event.type for event in planted.events[-4:]],
            ['robot_arrived', 'inventory_updated', 'crop_planted', 'task_completed'],
        )

        revision = planted.revision
        retried = store.assign_task(request)
        simulator.tick()
        unchanged = store.snapshot()
        self.assertEqual(retried.id, task.id)
        self.assertEqual(retried.status, 'COMPLETED')
        self.assertEqual(unchanged.revision, revision)
        self.assertEqual(unchanged.robots[0].game.inventory['seeds'].quantity, 1)

        reset = store.reset_game()
        self.assertEqual(reset.farm.plots[0].status, 'EMPTY')
        self.assertEqual(reset.robots[0].game.inventory['seeds'].quantity, 2)

    def test_later_crops_complete_plant_grow_harvest_sell_lifecycle(self):
        for crop_id, seed_id, stage, grow_seconds, sell_price in (
            ('carrot', 'carrot_seeds', 2, 12, 20),
            ('pumpkin', 'pumpkin_seeds', 3, 18, 32),
        ):
            with self.subTest(crop_id=crop_id):
                world = default_world()
                world['game']['stage'] = stage
                world['robots'][0]['game']['inventory'][seed_id] = {
                    'name': f'{crop_id.title()} Seeds',
                    'quantity': 1,
                    'sell_price': None,
                }
                store = WorldStore(world)
                store.start_game()
                simulator = SimulationRunner(
                    store,
                    interval_seconds=2.5,
                    step_distance=100,
                )
                store.assign_task(TaskRequest(
                    request_id=f'plant-{crop_id}',
                    robot_id='robot-a',
                    action='PLANT',
                    location='farm',
                    parameters={'item': seed_id, 'plot_id': 'plot-1'},
                ))

                simulator.tick()

                planted = store.snapshot().farm.plots[0]
                self.assertEqual(planted.status, 'GROWING')
                self.assertEqual(planted.crop_id, crop_id)
                self.assertEqual(
                    planted.ready_at - planted.planted_at,
                    timedelta(seconds=grow_seconds),
                )

                store.advance_crop_growth(planted.ready_at)
                store.assign_task(TaskRequest(
                    request_id=f'harvest-{crop_id}',
                    robot_id='robot-a',
                    action='HARVEST',
                    location='farm',
                    parameters={'plot_id': 'plot-1'},
                ))
                simulator.tick()
                simulator.tick()

                harvested = store.snapshot()
                crop = harvested.robots[0].game.inventory[crop_id]
                self.assertEqual(crop.quantity, 3)
                self.assertEqual(crop.sell_price, sell_price)
                self.assertEqual(harvested.farm.plots[0].status, 'EMPTY')

                store.assign_task(TaskRequest(
                    request_id=f'sell-{crop_id}',
                    robot_id='robot-a',
                    action='SELL',
                    location='market',
                    parameters={'item': crop_id, 'quantity': 3},
                ))
                simulator.tick()

                sold = store.snapshot().robots[0]
                self.assertNotIn(crop_id, sold.game.inventory)
                self.assertEqual(sold.game.money, 40 + 3 * sell_price)

    def test_competing_plant_rechecks_plot_before_consuming_seed(self):
        world = default_world()
        for robot in world['robots']:
            robot['game']['inventory']['seeds'] = {
                'name': 'Wheat Seeds',
                'quantity': 1,
                'sell_price': None,
            }
        store = WorldStore(world)
        store.start_game()
        for robot_id in ('robot-a', 'robot-b'):
            store.assign_task(TaskRequest(
                request_id=f'simulation-plant-{robot_id}',
                robot_id=robot_id,
                action='PLANT',
                location='farm',
                parameters={'item': 'seeds', 'plot_id': 'plot-1'},
            ))

        SimulationRunner(store, step_distance=100).tick()

        planted = store.snapshot()
        self.assertNotIn('seeds', planted.robots[0].game.inventory)
        self.assertEqual(planted.robots[1].game.inventory['seeds'].quantity, 1)
        self.assertEqual(planted.farm.plots[0].planted_by, 'robot-a')
        self.assertIsNone(planted.robots[0].task)
        self.assertIsNone(planted.robots[1].task)
        self.assertEqual(planted.events[-1].type, 'task_failed')
        self.assertEqual(planted.events[-1].data['code'], 'PLOT_OCCUPIED')

    def test_cancelled_plant_does_not_consume_seed(self):
        world = default_world()
        world['robots'][0]['game']['inventory']['seeds'] = {
            'name': 'Wheat Seeds',
            'quantity': 1,
            'sell_price': None,
        }
        store = WorldStore(world)
        store.start_game()
        store.assign_task(TaskRequest(
            request_id='simulation-plant-cancelled',
            robot_id='robot-a',
            action='PLANT',
            location='farm',
            parameters={'item': 'seeds', 'plot_id': 'plot-1'},
        ))

        store.stop_game()

        stopped = store.snapshot()
        self.assertEqual(stopped.robots[0].game.inventory['seeds'].quantity, 1)
        self.assertEqual(stopped.farm.plots[0].status, 'EMPTY')

    def test_crop_becomes_ready_once_at_backend_timestamp(self):
        world = default_world()
        planted_at = datetime.now(timezone.utc)
        ready_at = planted_at + timedelta(seconds=8)
        world['farm']['plots'][0].update({
            'status': 'GROWING',
            'crop_id': 'wheat',
            'planted_by': 'robot-a',
            'planted_at': planted_at,
            'ready_at': ready_at,
        })
        store = WorldStore(world)
        store.start_game()
        revision = store.snapshot().revision

        too_early = store.advance_crop_growth(ready_at - timedelta(microseconds=1))
        self.assertEqual(too_early.revision, revision)
        self.assertEqual(too_early.farm.plots[0].status, 'GROWING')

        ready = store.advance_crop_growth(ready_at)
        self.assertEqual(ready.revision, revision + 1)
        self.assertEqual(ready.farm.plots[0].status, 'READY')
        self.assertEqual(ready.events[-1].type, 'crop_ready')
        self.assertEqual(ready.events[-1].robot_id, 'robot-a')
        self.assertEqual(ready.events[-1].data['plot_id'], 'plot-1')

        duplicate = store.advance_crop_growth(ready_at + timedelta(seconds=1))
        self.assertEqual(duplicate.revision, ready.revision)
        self.assertEqual(
            sum(event.type == 'crop_ready' for event in duplicate.events),
            1,
        )

    def test_crop_growth_requires_timezone_aware_clock(self):
        store = WorldStore()
        store.start_game()

        with self.assertRaisesRegex(ValueError, 'timezone'):
            store.advance_crop_growth(datetime.now())

    def test_elapsed_crop_becomes_ready_after_game_resumes(self):
        world = default_world()
        planted_at = datetime.now(timezone.utc)
        ready_at = planted_at + timedelta(seconds=8)
        world['farm']['plots'][0].update({
            'status': 'GROWING',
            'crop_id': 'wheat',
            'planted_by': 'robot-a',
            'planted_at': planted_at,
            'ready_at': ready_at,
        })
        store = WorldStore(world)
        store.start_game()
        store.stop_game()

        stopped = store.advance_crop_growth(ready_at)
        self.assertEqual(stopped.farm.plots[0].status, 'GROWING')

        store.start_game()
        resumed = store.advance_crop_growth(ready_at)
        self.assertEqual(resumed.farm.plots[0].status, 'READY')
        self.assertEqual(resumed.events[-1].type, 'crop_ready')

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
        self.assertEqual(milo.game.money, 24)
        self.assertEqual(completed.game.goal.current, 64)
        self.assertEqual(completed.game.stage, 1)
        self.assertEqual(completed.events[-1].type, 'task_completed')

        revision = completed.revision
        simulator.tick()
        self.assertEqual(store.snapshot().revision, revision)
        self.assertEqual(store.snapshot().robots[1].game.money, 24)

    def test_sale_cannot_complete_goal_before_final_stage(self):
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
        self.assertEqual(completed.game.status, 'RUNNING')
        self.assertEqual(completed.game.goal.current, 64)
        self.assertIsNotNone(completed.robots[0].task)
        self.assertIsNone(completed.robots[1].task)
        self.assertNotIn('task_cancelled', [event.type for event in completed.events])
        self.assertEqual(completed.events[-1].type, 'task_completed')

    def test_clean_round_collects_sells_and_completes_shared_goal_once(self):
        world = default_world()
        world['robots'][1]['game'].update(money=40, inventory={})
        world['game']['goal']['current'] = 80
        world['fishing'] = {
            'min_duration_seconds': 2.5,
            'max_duration_seconds': 2.5,
            'tiers': [{
                'id': 'fish',
                'name': 'Salmon',
                'sell_price': 18,
                'probability': 1,
            }],
        }
        world['game']['goal']['target'] = 115
        ready_plot_ids = [
            ready_wheat_plot(world, plot_index)
            for plot_index in range(2)
        ]
        store = WorldStore(world)
        initial = store.snapshot()
        self.assertEqual(initial.game.status, 'READY')
        self.assertEqual(initial.game.stage, 1)
        self.assertEqual(initial.game.goal.current, 80)
        self.assertEqual(initial.game.goal.target, 115)
        self.assertTrue(all(robot.game.location == 'homebase' for robot in initial.robots))
        self.assertTrue(all(robot.game.inventory == {} for robot in initial.robots))

        store.start_game()
        simulator = SimulationRunner(
            store,
            interval_seconds=2.5,
            step_distance=100,
        )

        request_number = 0

        def collect(robot_id, action, location, parameters=None):
            nonlocal request_number
            request_number += 1
            store.assign_task(TaskRequest(
                request_id=f'clean-round-collect-{request_number}',
                robot_id=robot_id,
                action=action,
                location=location,
                parameters=parameters or {},
            ))
            simulator.tick()
            simulator.tick()

        for plot_id in ready_plot_ids:
            collect('robot-a', 'HARVEST', 'farm', {'plot_id': plot_id})
        for _ in range(3):
            collect('robot-b', 'FISH', 'lake')

        collected = store.snapshot()
        self.assertEqual(collected.robots[0].game.inventory['wheat'].quantity, 6)
        self.assertEqual(collected.robots[1].game.inventory['fish'].quantity, 3)
        self.assertEqual(collected.game.goal.current, 80)

        store.assign_task(TaskRequest(
            request_id='clean-round-sell-wheat',
            robot_id='robot-a',
            action='SELL',
            location='market',
            parameters={'item': 'wheat', 'quantity': 6},
        ))
        simulator.tick()
        after_wheat = store.snapshot()
        self.assertEqual(after_wheat.game.status, 'RUNNING')
        self.assertEqual(after_wheat.game.goal.current, 152)
        self.assertEqual(after_wheat.game.stage, 1)
        self.assertNotIn('wheat', after_wheat.robots[0].game.inventory)

        stage_two = store.propose_stage_unlock(StageUnlockProposalRequest(
            request_id='clean-round-propose-stage-two',
            proposer_id='robot-a',
            stage=2,
            contributions={'robot-a': 15, 'robot-b': 15},
        ))
        store.respond_stage_unlock(stage_two.id, EconomyResponseRequest(
            request_id='clean-round-accept-stage-two',
            robot_id='robot-b',
            accepted=True,
        ))

        store.assign_task(TaskRequest(
            request_id='clean-round-sell-fish',
            robot_id='robot-b',
            action='SELL',
            location='market',
            parameters={'item': 'fish', 'quantity': 2},
        ))
        simulator.tick()
        after_fish = store.snapshot()
        self.assertEqual(after_fish.game.status, 'RUNNING')
        self.assertEqual(after_fish.game.goal.current, 158)
        self.assertEqual(after_fish.game.stage, 2)

        stage_three = store.propose_stage_unlock(StageUnlockProposalRequest(
            request_id='clean-round-propose-stage-three',
            proposer_id='robot-b',
            stage=3,
            contributions={'robot-a': 30, 'robot-b': 30},
        ))
        store.respond_stage_unlock(stage_three.id, EconomyResponseRequest(
            request_id='clean-round-accept-stage-three',
            robot_id='robot-a',
            accepted=True,
        ))

        store.assign_task(TaskRequest(
            request_id='clean-round-sell-final-fish',
            robot_id='robot-b',
            action='SELL',
            location='market',
            parameters={'item': 'fish', 'quantity': 1},
        ))
        simulator.tick()
        completed = store.snapshot()
        self.assertEqual(completed.game.status, 'COMPLETED')
        self.assertEqual(completed.game.goal.current, 116)
        self.assertEqual(completed.robots[0].game.money, 67)
        self.assertEqual(completed.robots[1].game.money, 49)
        self.assertNotIn('fish', completed.robots[1].game.inventory)
        self.assertEqual(
            sum(event.type == 'game_completed' for event in completed.events),
            1,
        )
        self.assertEqual(
            [event.data['item'] for event in completed.events if event.type == 'stage_unlocked'],
            ['carrot_seeds', 'pumpkin_seeds'],
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
        world = default_world()
        world['robots'][1]['game'].update(money=40, inventory={})
        world['game']['goal']['current'] = 80
        store = WorldStore(world)
        store.start_game()
        store.assign_task(TaskRequest(
            request_id='simulation-buy-001',
            robot_id='robot-b',
            action='BUY',
            location='market',
            parameters={'item': 'seeds', 'quantity': 1},
        ))
        simulator = SimulationRunner(store, step_distance=100)

        simulator.tick()
        completed = store.snapshot()
        milo = completed.robots[1]
        seeds = milo.game.inventory['seeds']
        market_seeds = next(
            item for item in completed.market.items if item.id == 'seeds'
        )
        self.assertIsNone(milo.task)
        self.assertEqual(milo.game.money, 35)
        self.assertEqual(seeds.quantity, 1)
        self.assertIsNone(seeds.sell_price)
        self.assertIsNone(market_seeds.stock)
        self.assertEqual(completed.game.goal.current, 75)
        self.assertEqual(completed.events[-1].type, 'task_completed')

        revision = completed.revision
        simulator.tick()
        self.assertEqual(store.snapshot().revision, revision)

    def test_competing_purchase_rechecks_stock_at_execution(self):
        world = default_world()
        world['robots'][1]['game'].update(money=40, inventory={})
        world['game']['goal']['current'] = 80
        world['game']['stage'] = 3
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
