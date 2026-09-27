"""Shared definitions for backend-owned collection activities."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActivityDefinition:
    location: str
    duration_seconds: float
    item_id: str
    item_name: str
    quantity: int
    sell_price: int
    label: str


ACTIVITIES = {
    'HARVEST': ActivityDefinition(
        location='farm',
        duration_seconds=2.5,
        item_id='wheat',
        item_name='Wheat',
        quantity=3,
        sell_price=12,
        label='harvesting wheat',
    ),
    'FISH': ActivityDefinition(
        location='lake',
        duration_seconds=2.5,
        item_id='fish',
        item_name='Salmon',
        quantity=1,
        sell_price=18,
        label='fishing',
    ),
}


def activity_for(action: str) -> ActivityDefinition | None:
    return ACTIVITIES.get(action)
