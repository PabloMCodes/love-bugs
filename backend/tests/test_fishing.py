from random import Random
import unittest

from pydantic import ValidationError

from app.game.fishing import (
    DEFAULT_FISHING,
    expected_fishing_gold_per_second,
    resolve_fishing_attempt,
)
from app.schemas import TaskRequest, WorldSnapshot
from app.simulation.simulator import SimulationRunner
from app.state import WorldStore, default_world


class FixedRandom:
    def __init__(self, duration, roll):
        self.duration = duration
        self.roll = roll

    def uniform(self, start, end):
        if not start <= self.duration <= end:
            raise AssertionError('Fixed duration is outside configured bounds')
        return self.duration

    def random(self):
        return self.roll


class FishingRuleTests(unittest.TestCase):
    def test_seeded_attempts_are_reproducible_and_bounded(self):
        first_rng = Random(12345)
        second_rng = Random(12345)

        first = [resolve_fishing_attempt(DEFAULT_FISHING, first_rng) for _ in range(8)]
        second = [resolve_fishing_attempt(DEFAULT_FISHING, second_rng) for _ in range(8)]

        self.assertEqual(first, second)
        self.assertTrue(all(5 <= attempt.duration_seconds <= 15 for attempt in first))

    def test_probability_boundaries_select_all_three_tiers(self):
        attempts = [
            resolve_fishing_attempt(DEFAULT_FISHING, FixedRandom(5, roll))
            for roll in (.0, .699999, .70, .949999, .95, .999999)
        ]

        self.assertEqual(
            [attempt.tier for attempt in attempts],
            [
                'common_fish',
                'common_fish',
                'uncommon_fish',
                'uncommon_fish',
                'rare_fish',
                'rare_fish',
            ],
        )

    def test_expected_value_uses_tier_weights_and_mean_duration(self):
        self.assertAlmostEqual(expected_fishing_gold_per_second(DEFAULT_FISHING), .27)

    def test_world_rejects_probabilities_that_do_not_total_one(self):
        world = default_world()
        world['fishing']['tiers'][0]['probability'] = .5

        with self.assertRaisesRegex(ValidationError, 'must total 1'):
            WorldSnapshot.model_validate(world)


class FishingLifecycleTests(unittest.TestCase):
    def test_task_locks_outcome_and_grants_it_exactly_once(self):
        store = WorldStore(fishing_rng=FixedRandom(7, .97))
        store.start_game()
        request = TaskRequest(
            request_id='seeded-fishing-attempt',
            robot_id='robot-a',
            action='FISH',
            location='lake',
        )

        assigned = store.assign_task(request)

        self.assertEqual(assigned.parameters, {
            'duration_seconds': 7.0,
            'catch': {
                'item_id': 'rare_fish',
                'item_name': 'Extremely Rare Fish',
                'sell_price': 15,
                'tier': 'rare_fish',
            },
        })
        SimulationRunner(store, step_distance=100).tick()
        store.advance_activities(6.9)
        self.assertAlmostEqual(store.snapshot().robots[0].task.progress, 6.9 / 7)
        store.advance_activities(.1)
        completed = store.snapshot()

        self.assertIsNone(completed.robots[0].task)
        self.assertEqual(completed.robots[0].game.inventory['rare_fish'].quantity, 1)
        self.assertEqual(completed.robots[0].game.inventory['rare_fish'].sell_price, 15)
        self.assertEqual(completed.events[-2].type, 'fish_caught')
        self.assertEqual(completed.events[-1].data['tier'], 'rare_fish')

        revision = completed.revision
        retried = store.assign_task(request)
        store.advance_activities(100)
        self.assertEqual(retried.id, assigned.id)
        self.assertEqual(retried.status, 'COMPLETED')
        self.assertEqual(store.snapshot().revision, revision)
        self.assertEqual(store.snapshot().robots[0].game.inventory['rare_fish'].quantity, 1)

    def test_cancelled_attempt_grants_no_catch(self):
        store = WorldStore(fishing_rng=FixedRandom(5, 0))
        store.start_game()
        task = store.assign_task(TaskRequest(
            request_id='cancelled-fishing-attempt',
            robot_id='robot-a',
            action='FISH',
            location='lake',
        ))
        SimulationRunner(store, step_distance=100).tick()

        store.stop_game()
        store.advance_activities(100)

        self.assertEqual(store.snapshot().robots[0].game.inventory, {})
        self.assertEqual(store.task(task.id).status, 'CANCELLED')


if __name__ == '__main__':
    unittest.main()
