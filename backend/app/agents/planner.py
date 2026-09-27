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

    message: str | None = Field(default=None, min_length=1, max_length=300,
                                description='Optional useful public dialogue; null when there is nothing new to say.')

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

    async def converse(self, world, robot_id, opener, topic):
        pairs = (
            ('If I had legs, I’d be quite tired by now.', 'Wheels were an excellent life choice.'),
            ('Do you think a wheel can have a favorite direction?', 'Mine seem pretty attached to forward.'),
            ('I think I’d look good in a tiny hat.', 'As long as it doesn’t cover your marker.'),
            ('Would a robot picnic need a blanket?', 'Only if we invite the crumbs.'),
            ('I could get used to this little world.', 'It’s a good size for the two of us.'),
            ('If we had pockets, what would you keep in yours?', 'A spare pocket. Just in case.'),
            ('Do you ever wish you could skip?', 'I’d settle for a dignified little wobble.'),
            ('I’ve decided rolling counts as dancing.', 'Then we’ve been rehearsing all day.'),
            ('A tiny bench would look nice here.', 'We could park beside it very thoughtfully.'),
            ('I wonder if fish think we’re strange.', 'We do bring our own wheels everywhere.'),
        )
        return pairs[topic % len(pairs)][1 if opener else 0]

    async def decide(self, world: dict, robot_id: str) -> Decision:
        robot = get_robot(world, robot_id)
        for item_id in robot['game']['inventory']:
            quantity = inventory_quantity(robot, item_id)
            if quantity > 0 and valid_price(inventory_sell_price(world, robot, item_id)):
                return Decision(action='SELL', location='market', item=item_id,
                                quantity=quantity, reason='Sell inventory toward our shared gold goal.',
                                message=f'I’ll sell {quantity} {item_id} from my inventory while you keep collecting.')
        index = [robot['id'] for robot in world['robots']].index(robot_id)
        action, location = ('HARVEST', 'farm') if index % 2 == 0 else ('FISH', 'lake')
        heard = world.get('agent_messages', [])
        peer = next((m for m in reversed(heard) if m.get('robot_id') != robot_id), None)
        message = f'I’ll cover the {location}.'
        if peer and peer.get('action') == 'SELL':
            message = f'I’ll keep collecting at the {location} while you sell.'
        elif peer and peer.get('location') and peer['location'] != location:
            message = f'You’ve got the {peer["location"]}; I’ll cover the {location}.'
        return Decision(action=action, location=location,
                        message=message,
                        reason='Collect resources while my teammate covers the other location.')
