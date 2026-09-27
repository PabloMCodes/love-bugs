"""Per-robot decisions and deterministic checks against the shared task contract."""

import math
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')

    action: Literal['MOVE_TO', 'HARVEST', 'FISH', 'BUY', 'SELL', 'RETURN_HOME', 'WAIT']
    location: str | None = None
    item: str | None = None
    quantity: int | None = Field(default=None, strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=300)

    message: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode='after')
    def check_parameters(self):
        if self.message is not None and not self.message.strip():
            raise ValueError('Public messages must not be blank')
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


def available(world: dict, robot: dict, *, discussion: bool = False) -> bool:
    physical = robot['physical']
    goal = world['game']['goal']
    return (
        world['game']['status'] in (('READY', 'RUNNING') if discussion else ('RUNNING',))
        and goal['current'] < goal['target']
        and physical['online']
        and not physical['stopped']
        and not physical['blocked']
        and physical['tracking'] == 'TRACKED'
        and physical['pose'] is not None
        and robot['task'] is None
    )


def inventory_quantity(robot: dict, item: str) -> int:
    # Accept canonical display-rich inventory and older bare-count dev fixtures.
    value = robot['game']['inventory'].get(item, 0)
    return value.get('quantity', 0) if isinstance(value, dict) else value


def inventory_sell_price(world: dict, robot: dict, item: str):
    value = robot['game']['inventory'].get(item)
    if isinstance(value, dict):
        return value.get('sell_price')

    # Older development fixtures represented inventory as bare counts and kept
    # prices in the market list. Canonical snapshots carry sell_price on inventory.
    market_item = next(
        (candidate for candidate in world['market']['items'] if candidate['id'] == item),
        None,
    )
    return market_item.get('sell_price') if market_item is not None else None


def valid_price(price) -> bool:
    return (
        isinstance(price, (int, float))
        and not isinstance(price, bool)
        and math.isfinite(price)
        and price >= 0
    )


def validate_decision(world: dict, robot_id: str, decision: Decision, *, discussion: bool = False) -> None:
    robot = get_robot(world, robot_id)
    if not available(world, robot, discussion=discussion):
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
    if decision.action == 'BUY':
        item = next(
            (item for item in world['market']['items'] if item['id'] == decision.item),
            None,
        )
        if item is None:
            raise ValueError('Unknown market item')
        if world['game'].get('stage', 1) < item.get('required_stage', 1):
            raise ValueError('Item is locked for the current farming stage')
        price = item['buy_price']
        if not valid_price(price):
            raise ValueError('Item is unavailable for this trade')
        if robot['game']['money'] < price * decision.quantity:
            raise ValueError('Insufficient gold')
        if item['stock'] is not None and item['stock'] < decision.quantity:
            raise ValueError('Insufficient stock')
    else:
        if inventory_quantity(robot, decision.item) < decision.quantity:
            raise ValueError('Insufficient inventory')
        if not valid_price(inventory_sell_price(world, robot, decision.item)):
            raise ValueError('Item is unavailable for sale')


class MockPlanner:
    """Explicit offline demo policy, never a silent substitute for Gemini."""

    async def decide(self, world: dict, robot_id: str) -> Decision:
        robot = get_robot(world, robot_id)
        for item_id in robot['game']['inventory']:
            quantity = inventory_quantity(robot, item_id)
            if quantity > 0 and valid_price(inventory_sell_price(world, robot, item_id)):
                return Decision(action='SELL', location='market', item=item_id,
                                quantity=quantity, reason='Sell inventory toward our shared gold goal.',
                                message='I propose selling my inventory. Can you keep collecting resources?')
        index = [robot['id'] for robot in world['robots']].index(robot_id)
        action, location = ('HARVEST', 'farm') if index % 2 == 0 else ('FISH', 'lake')
        heard = world.get('agent_messages', [])
        reply = 'Got it, teammate! ' if heard else 'Team, here is my plan: '
        return Decision(action=action, location=location,
                        message=f'{reply}I propose collecting at the {location}. Let’s cover both spots.',
                        reason='Collect resources while my teammate covers the other location.')
