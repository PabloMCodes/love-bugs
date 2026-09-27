"""Seedable fishing outcomes resolved once when a fishing task is accepted."""

from copy import deepcopy
from dataclasses import dataclass
import math
from random import Random
from typing import Protocol


class RandomSource(Protocol):
    def random(self) -> float: ...

    def uniform(self, start: float, end: float) -> float: ...


@dataclass(frozen=True)
class FishingAttempt:
    duration_seconds: float
    item_id: str
    item_name: str
    sell_price: int
    tier: str

    def task_parameters(self) -> dict:
        return {
            'duration_seconds': self.duration_seconds,
            'catch': {
                'item_id': self.item_id,
                'item_name': self.item_name,
                'sell_price': self.sell_price,
                'tier': self.tier,
            },
        }


DEFAULT_FISHING = {
    'min_duration_seconds': 5,
    'max_duration_seconds': 15,
    'tiers': [
        {
            'id': 'common_fish',
            'name': 'Common Fish',
            'sell_price': 1,
            'probability': .70,
        },
        {
            'id': 'uncommon_fish',
            'name': 'Uncommon Fish',
            'sell_price': 5,
            'probability': .25,
        },
        {
            'id': 'rare_fish',
            'name': 'Extremely Rare Fish',
            'sell_price': 15,
            'probability': .05,
        },
    ],
}


def default_fishing() -> dict:
    """Return a fresh fishing-rule mapping for a new world session."""
    return deepcopy(DEFAULT_FISHING)


def resolve_fishing_attempt(
    fishing: dict,
    rng: RandomSource | None = None,
) -> FishingAttempt:
    random_source = rng if rng is not None else Random()
    duration = round(random_source.uniform(
        fishing['min_duration_seconds'],
        fishing['max_duration_seconds'],
    ), 3)
    roll = random_source.random()
    cumulative = 0.0
    selected = fishing['tiers'][-1]
    for tier in fishing['tiers']:
        cumulative += tier['probability']
        if roll < cumulative:
            selected = tier
            break
    return FishingAttempt(
        duration_seconds=duration,
        item_id=selected['id'],
        item_name=selected['name'],
        sell_price=selected['sell_price'],
        tier=selected['id'],
    )


def expected_fishing_gold_per_second(fishing: dict) -> float:
    expected_value = sum(
        tier['sell_price'] * tier['probability']
        for tier in fishing['tiers']
    )
    expected_duration = (
        fishing['min_duration_seconds'] + fishing['max_duration_seconds']
    ) / 2
    if not math.isfinite(expected_duration) or expected_duration <= 0:
        return 0
    return expected_value / expected_duration
