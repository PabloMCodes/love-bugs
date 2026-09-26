"""Per-robot decisions and deterministic checks against the shared task contract."""

import math
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')

    action: Literal['MOVE_TO', 'HARVEST', 'FISH', 'BUY', 'SELL', 'RETURN_HOME', 'WAIT']
    location: str | None = None
    item: str | None = None
    quantity: int | None = Field(default=None, strict=True, gt=0)
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode='after')
    def check_parameters(self):
        if not self.reason.strip():
            raise ValueError('A decision must explain its purpose')
        if self.action == 'WAIT':
            if any(value is not None for value in (self.location, self.item, self.quantity)):
                raise ValueError('WAIT has no task parameters')
        elif not self.location:
            raise ValueError('A task requires a location')
        if self.action in ('BUY', 'SELL'):
            if not self.item or self.quantity is None:
                raise ValueError('Trades require an item and positive integer quantity')
        elif self.item is not None or self.quantity is not None:
            raise ValueError('Only trades accept item/quantity')
        return self


class Planner(Protocol):
    async def decide(self, world: dict, robot_id: str) -> Decision: ...


def get_robot(world: dict, robot_id: str) -> dict:
    return next(robot for robot in world['robots'] if robot['id'] == robot_id)


def available(world: dict, robot: dict) -> bool:
    physical = robot['physical']
    goal = world['game']['goal']
    return (
        world['game']['status'] == 'RUNNING'
        and goal['current'] < goal['target']
        and physical['online']
        and not physical['stopped']
        and not physical['blocked']
        and physical['tracking'] == 'TRACKED'
        and physical['pose'] is not None
        and robot['task'] is None
    )


def inventory_quantity(robot: dict, item: str) -> int:
    # Accept the canonical numeric inventory and dev's display-rich mock inventory.
    value = robot['game']['inventory'].get(item, 0)
    return value.get('quantity', 0) if isinstance(value, dict) else value


def validate_decision(world: dict, robot_id: str, decision: Decision) -> None:
    robot = get_robot(world, robot_id)
    if not available(world, robot):
        raise ValueError('Robot or game is unavailable for a new task')
    if decision.action == 'WAIT':
        return
    if decision.location not in world['map']['locations']:
        raise ValueError('Unknown destination')
    required = {'HARVEST': 'farm', 'FISH': 'lake', 'BUY': 'market',
                'SELL': 'market', 'RETURN_HOME': 'homebase'}
    if decision.action in required and decision.location != required[decision.action]:
        raise ValueError('Action does not match its destination')
    if decision.action not in ('BUY', 'SELL'):
        return
    item = next((item for item in world['market']['items'] if item['id'] == decision.item), None)
    if item is None:
        raise ValueError('Unknown market item')
    price = item['buy_price' if decision.action == 'BUY' else 'sell_price']
    if price is None or not math.isfinite(price) or price < 0:
        raise ValueError('Item is unavailable for this trade')
    if decision.action == 'BUY':
        if robot['game']['money'] < price * decision.quantity:
            raise ValueError('Insufficient gold')
        if item['stock'] is not None and item['stock'] < decision.quantity:
            raise ValueError('Insufficient stock')
    elif inventory_quantity(robot, decision.item) < decision.quantity:
        raise ValueError('Insufficient inventory')


class MockPlanner:
    """Explicit offline demo policy, never a silent substitute for Gemini."""

    async def decide(self, world: dict, robot_id: str) -> Decision:
        robot = get_robot(world, robot_id)
        for item in world['market']['items']:
            quantity = inventory_quantity(robot, item['id'])
            if quantity > 0 and item['sell_price'] is not None:
                return Decision(action='SELL', location='market', item=item['id'],
                                quantity=quantity, reason='Sell inventory toward our shared gold goal.')
        index = [robot['id'] for robot in world['robots']].index(robot_id)
        action, location = ('HARVEST', 'farm') if index % 2 == 0 else ('FISH', 'lake')
        return Decision(action=action, location=location,
                        reason='Collect resources while my teammate covers the other location.')
