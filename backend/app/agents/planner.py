"""Per-robot decisions and deterministic checks against the shared task contract."""

from collections import Counter
import math
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')

    action: Literal[
        'MOVE_TO',
        'HARVEST',
        'FISH',
        'BUY',
        'SELL',
        'PLANT',
        'RETURN_HOME',
        'WAIT',
    ]
    location: str | None = None
    item: str | None = None
    quantity: int | None = Field(default=None, strict=True, ge=1)
    plot_id: str | None = None
    reason: str = Field(min_length=1, max_length=300)

    message: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode='after')
    def check_parameters(self):
        if self.message is not None and not self.message.strip():
            raise ValueError('Public messages must not be blank')
        if not self.reason.strip():
            raise ValueError('A decision must explain its purpose')
        if self.action == 'WAIT':
            if any(value is not None for value in (
                self.location,
                self.item,
                self.quantity,
                self.plot_id,
            )):
                raise ValueError('WAIT has no task parameters')
        elif not self.location:
            raise ValueError('A task requires a location')
        if self.action in ('BUY', 'SELL'):
            if not self.item or self.quantity is None:
                raise ValueError('Trades require an item and positive integer quantity')
            if self.plot_id is not None:
                raise ValueError('Trades do not accept plot_id')
        elif self.action == 'PLANT':
            if not self.item or not self.plot_id:
                raise ValueError('PLANT requires an item and plot_id')
            if self.quantity is not None:
                raise ValueError('PLANT does not accept quantity')
        elif self.action == 'HARVEST':
            if not self.plot_id:
                raise ValueError('HARVEST requires a plot_id')
            if self.item is not None or self.quantity is not None:
                raise ValueError('HARVEST accepts only plot_id')
        elif any(value is not None for value in (self.item, self.quantity, self.plot_id)):
            raise ValueError('This action does not accept item, quantity, or plot_id')
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
    required = {
        'HARVEST': 'farm',
        'FISH': 'lake',
        'BUY': 'market',
        'SELL': 'market',
        'PLANT': 'farm',
        'RETURN_HOME': 'homebase',
    }
    if decision.action in required and decision.location != required[decision.action]:
        raise ValueError('Action does not match its destination')
    if decision.action == 'HARVEST':
        plot = next(
            (
                plot for plot in world['farm']['plots']
                if plot['id'] == decision.plot_id
            ),
            None,
        )
        if plot is None:
            raise ValueError('Unknown farm plot')
        if plot['status'] != 'READY':
            raise ValueError('Farm plot is not ready')
        if any(
            candidate.get('task')
            and candidate['task'].get('action') == 'HARVEST'
            and candidate['task'].get('parameters', {}).get('plot_id')
            == decision.plot_id
            for candidate in world['robots']
        ):
            raise ValueError('Farm plot is already claimed for harvest')
        return
    if decision.action == 'PLANT':
        crop = next(
            (
                crop for crop in world['farm']['crops']
                if crop['seed_item_id'] == decision.item
            ),
            None,
        )
        if crop is None:
            raise ValueError('Unknown crop seed')
        if world['game'].get('stage', 1) < crop.get('required_stage', 1):
            raise ValueError('Crop is locked for the current farming stage')
        if inventory_quantity(robot, decision.item) < 1:
            raise ValueError('Seed is not in this robot inventory')
        plot = next(
            (
                plot for plot in world['farm']['plots']
                if plot['id'] == decision.plot_id
            ),
            None,
        )
        if plot is None:
            raise ValueError('Unknown farm plot')
        if plot['status'] != 'EMPTY':
            raise ValueError('Farm plot is not empty')
        if any(
            candidate.get('task')
            and candidate['task'].get('action') == 'PLANT'
            and candidate['task'].get('parameters', {}).get('plot_id')
            == decision.plot_id
            for candidate in world['robots']
        ):
            raise ValueError('Farm plot is already claimed for planting')
        return
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
        claimed_plots = {
            candidate['task']['parameters'].get('plot_id')
            for candidate in world['robots']
            if candidate.get('task')
            and candidate['task'].get('action') == 'HARVEST'
        }
        ready_plot = next(
            (
                plot for plot in world.get('farm', {}).get('plots', [])
                if plot['status'] == 'READY' and plot['id'] not in claimed_plots
            ),
            None,
        )
        heard = world.get('agent_messages', [])
        reply = 'Got it, teammate! ' if heard else 'Team, here is my plan: '
        if ready_plot is not None:
            return Decision(
                action='HARVEST',
                location='farm',
                plot_id=ready_plot['id'],
                message=f"{reply}I propose harvesting {ready_plot['id']} while it is ready.",
                reason='Harvest a ready crop before starting other work.',
            )

        plant_claims = {
            candidate['task']['parameters'].get('plot_id')
            for candidate in world['robots']
            if candidate.get('task')
            and candidate['task'].get('action') == 'PLANT'
        }
        empty_plots = [
            plot for plot in world.get('farm', {}).get('plots', [])
            if plot['status'] == 'EMPTY' and plot['id'] not in plant_claims
        ]
        stage = world['game'].get('stage', 1)
        market_by_id = {
            item['id']: item
            for item in world.get('market', {}).get('items', [])
        }
        crops = [
            crop for crop in world.get('farm', {}).get('crops', [])
            if stage >= crop.get('required_stage', 1)
        ]

        def crop_priority(crop: dict) -> tuple[float, int, int]:
            market_item = market_by_id.get(crop['seed_item_id'], {})
            seed_price = market_item.get('buy_price')
            gross_value = (
                crop.get('harvest_quantity', 0)
                * crop.get('sell_price', 0)
            )
            profit = (
                gross_value - seed_price
                if valid_price(seed_price)
                else gross_value
            )
            grow_seconds = crop.get('grow_seconds', 0)
            profit_rate = (
                profit / grow_seconds
                if isinstance(grow_seconds, (int, float)) and grow_seconds > 0
                else 0
            )
            return profit_rate, profit, crop.get('required_stage', 1)

        crops.sort(
            key=crop_priority,
            reverse=True,
        )
        if empty_plots:
            owned_crop = next(
                (
                    crop for crop in crops
                    if inventory_quantity(robot, crop['seed_item_id']) > 0
                ),
                None,
            )
            if owned_crop is not None:
                plot = empty_plots[0]
                return Decision(
                    action='PLANT',
                    location='farm',
                    item=owned_crop['seed_item_id'],
                    plot_id=plot['id'],
                    message=(
                        f"{reply}I propose planting {owned_crop['name']} "
                        f"in {plot['id']}."
                    ),
                    reason='Fill an empty plot with an owned seed.',
                )

            reserved_seeds = Counter(
                candidate['task']['parameters'].get('item')
                for candidate in world['robots']
                if candidate.get('task')
                and candidate['task'].get('action') == 'PLANT'
            )
            pending_buys = Counter(
                candidate['task']['parameters'].get('item')
                for candidate in world['robots']
                if candidate.get('task')
                and candidate['task'].get('action') == 'BUY'
            )
            seed_ids = {crop['seed_item_id'] for crop in crops}
            available_seeds = sum(
                max(
                    0,
                    sum(
                        inventory_quantity(candidate, seed_id)
                        for candidate in world['robots']
                    )
                    - reserved_seeds[seed_id],
                )
                + pending_buys[seed_id]
                for seed_id in seed_ids
            )
            if available_seeds < len(empty_plots):
                crop_to_buy = next(
                    (
                        crop for crop in crops
                        if crop['seed_item_id'] in market_by_id
                        and valid_price(
                            market_by_id[crop['seed_item_id']].get('buy_price')
                        )
                        and stage >= market_by_id[crop['seed_item_id']].get(
                            'required_stage',
                            1,
                        )
                        and crop.get('harvest_quantity', 0)
                        * crop.get('sell_price', 0)
                        > market_by_id[crop['seed_item_id']]['buy_price']
                        and robot['game']['money']
                        >= market_by_id[crop['seed_item_id']]['buy_price']
                        and (
                            market_by_id[crop['seed_item_id']].get('stock') is None
                            or market_by_id[crop['seed_item_id']]['stock']
                            > pending_buys[crop['seed_item_id']]
                        )
                    ),
                    None,
                )
                if crop_to_buy is not None:
                    seed = market_by_id[crop_to_buy['seed_item_id']]
                    return Decision(
                        action='BUY',
                        location='market',
                        item=seed['id'],
                        quantity=1,
                        message=(
                            f"{reply}I propose buying {seed['name']} "
                            'for an empty plot.'
                        ),
                        reason='Buy one seed for available farm capacity.',
                    )
        return Decision(
            action='FISH',
            location='lake',
            message=f'{reply}I propose fishing while no crop is ready.',
            reason='Collect fish while waiting for a ready farm plot.',
        )
