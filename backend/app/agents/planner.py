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
        'PROPOSE_UNLOCK',
        'RESPOND_UNLOCK',
        'TRANSFER_MONEY',
        'REQUEST_MONEY',
        'RESPOND_MONEY',
        'WAIT',
    ]
    location: str | None = None
    item: str | None = None
    quantity: int | None = Field(default=None, strict=True, ge=1)
    plot_id: str | None = None
    stage: int | None = Field(default=None, strict=True, ge=2, le=3)
    contributions: dict[str, int] | None = None
    proposal_id: str | None = None
    recipient_id: str | None = None
    amount: int | None = Field(default=None, strict=True, ge=1)
    money_request_id: str | None = None
    accepted: bool | None = None
    reason: str = Field(min_length=1, max_length=300)

    message: str | None = Field(default=None, min_length=1, max_length=300,
                                description='Optional useful public dialogue; null when there is nothing new to say.')

    @model_validator(mode='after')
    def check_parameters(self):
        if self.message is not None and not self.message.strip():
            raise ValueError('Public messages must not be blank')
        if not self.reason.strip():
            raise ValueError('A decision must explain its purpose')
        task_fields = (self.location, self.item, self.quantity, self.plot_id)
        economy_fields = (
            self.stage,
            self.contributions,
            self.proposal_id,
            self.recipient_id,
            self.amount,
            self.money_request_id,
            self.accepted,
        )
        economy_actions = {
            'PROPOSE_UNLOCK',
            'RESPOND_UNLOCK',
            'TRANSFER_MONEY',
            'REQUEST_MONEY',
            'RESPOND_MONEY',
        }
        if self.action == 'WAIT':
            if any(value is not None for value in (
                *task_fields,
                *economy_fields,
            )):
                raise ValueError('WAIT has no task parameters')
        elif self.action in economy_actions:
            if any(value is not None for value in task_fields):
                raise ValueError('Economy actions do not accept task parameters')
            required = {
                'PROPOSE_UNLOCK': (self.stage, self.contributions),
                'RESPOND_UNLOCK': (self.proposal_id, self.accepted),
                'TRANSFER_MONEY': (self.recipient_id, self.amount),
                'REQUEST_MONEY': (self.recipient_id, self.amount),
                'RESPOND_MONEY': (self.money_request_id, self.accepted),
            }[self.action]
            if any(value is None for value in required):
                raise ValueError(f'{self.action} is missing required economy parameters')
            allowed = {
                'PROPOSE_UNLOCK': {'stage', 'contributions'},
                'RESPOND_UNLOCK': {'proposal_id', 'accepted'},
                'TRANSFER_MONEY': {'recipient_id', 'amount'},
                'REQUEST_MONEY': {'recipient_id', 'amount'},
                'RESPOND_MONEY': {'money_request_id', 'accepted'},
            }[self.action]
            values = {
                'stage': self.stage,
                'contributions': self.contributions,
                'proposal_id': self.proposal_id,
                'recipient_id': self.recipient_id,
                'amount': self.amount,
                'money_request_id': self.money_request_id,
                'accepted': self.accepted,
            }
            if any(value is not None and name not in allowed for name, value in values.items()):
                raise ValueError(f'{self.action} has unrelated economy parameters')
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
        if self.action not in economy_actions and any(
            value is not None for value in economy_fields
        ):
            raise ValueError('Robot tasks do not accept economy parameters')
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
        and (goal['current'] < goal['target'] or world['game'].get('stage', 1) < 3)
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
    if decision.action == 'PROPOSE_UNLOCK':
        if decision.stage != world['game'].get('stage', 1) + 1:
            raise ValueError('Only the next stage can be proposed')
        rule = next(
            (
                item for item in world['economy']['unlocks']
                if item['stage'] == decision.stage
            ),
            None,
        )
        if rule is None or rule['unlocked']:
            raise ValueError('Stage unlock is unavailable')
        if any(
            proposal['status'] == 'PENDING'
            for proposal in world['economy']['unlock_proposals']
        ):
            raise ValueError('Another stage proposal is pending')
        if sum(candidate['game']['money'] for candidate in world['robots']) < rule['eligibility_gold']:
            raise ValueError('Stage is not eligible yet')
        robot_ids = {candidate['id'] for candidate in world['robots']}
        if set(decision.contributions or {}) != robot_ids:
            raise ValueError('Every robot must contribute')
        if any(
            isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0
            for amount in decision.contributions.values()
        ):
            raise ValueError('Contributions must be positive whole amounts')
        if sum(decision.contributions.values()) != rule['cost']:
            raise ValueError('Contributions do not match the unlock cost')
        if any(
            candidate['game']['money'] < decision.contributions[candidate['id']]
            for candidate in world['robots']
        ):
            raise ValueError('A robot cannot fund its contribution')
        return
    if decision.action == 'RESPOND_UNLOCK':
        proposal = next(
            (
                item for item in world['economy']['unlock_proposals']
                if item['id'] == decision.proposal_id
            ),
            None,
        )
        if proposal is None or proposal['status'] != 'PENDING':
            raise ValueError('Stage proposal is not pending')
        return
    if decision.action in ('TRANSFER_MONEY', 'REQUEST_MONEY'):
        if decision.recipient_id == robot_id:
            raise ValueError('Economy participants must be different robots')
        if not any(candidate['id'] == decision.recipient_id for candidate in world['robots']):
            raise ValueError('Unknown economy recipient')
        if decision.action == 'TRANSFER_MONEY' and robot['game']['money'] < decision.amount:
            raise ValueError('Insufficient gold')
        if decision.action == 'REQUEST_MONEY' and any(
            request['requester_id'] == robot_id and request['status'] == 'PENDING'
            for request in world['economy']['money_requests']
        ):
            raise ValueError('A money request is already pending')
        return
    if decision.action == 'RESPOND_MONEY':
        money_request = next(
            (
                item for item in world['economy']['money_requests']
                if item['id'] == decision.money_request_id
            ),
            None,
        )
        if (
            money_request is None
            or money_request['status'] != 'PENDING'
            or money_request['recipient_id'] != robot_id
        ):
            raise ValueError('Money request is not available to this robot')
        if decision.accepted and robot['game']['money'] < money_request['amount']:
            raise ValueError('Insufficient gold')
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
        pending_unlock = next(
            (
                proposal for proposal in world.get('economy', {}).get(
                    'unlock_proposals',
                    [],
                )
                if proposal['status'] == 'PENDING'
            ),
            None,
        )
        if pending_unlock is not None:
            if robot_id not in pending_unlock['accepted_by']:
                return Decision(
                    action='RESPOND_UNLOCK',
                    proposal_id=pending_unlock['id'],
                    accepted=True,
                    reason=f"Accept the shared Stage {pending_unlock['stage']} investment.",
                    message=f"I accept our Stage {pending_unlock['stage']} unlock plan.",
                )
            return Decision(
                action='WAIT',
                reason='Wait for the teammate to answer the stage proposal.',
                message='The unlock proposal is ready for your answer.',
            )

        pending_money = next(
            (
                request for request in world.get('economy', {}).get(
                    'money_requests',
                    [],
                )
                if request['status'] == 'PENDING'
                and robot_id in (request['requester_id'], request['recipient_id'])
            ),
            None,
        )
        if pending_money is not None:
            if pending_money['recipient_id'] == robot_id:
                can_afford = robot['game']['money'] >= pending_money['amount']
                return Decision(
                    action='RESPOND_MONEY',
                    money_request_id=pending_money['id'],
                    accepted=can_afford,
                    reason=(
                        'Fund the teammate request.'
                        if can_afford
                        else 'Decline a request that exceeds this wallet.'
                    ),
                    message=(
                        'I can help fund that.'
                        if can_afford
                        else 'I cannot afford that request yet.'
                    ),
                )
            return Decision(
                action='WAIT',
                reason='Wait for the teammate to answer the money request.',
                message='I am waiting for your funding decision.',
            )

        next_stage = world['game'].get('stage', 1) + 1
        unlock_rule = next(
            (
                rule for rule in world.get('economy', {}).get('unlocks', [])
                if rule['stage'] == next_stage and not rule['unlocked']
            ),
            None,
        )
        combined_gold = sum(candidate['game']['money'] for candidate in world['robots'])
        if unlock_rule is not None and combined_gold >= unlock_rule['eligibility_gold']:
            contributors = world['robots']
            contribution = unlock_rule['cost'] // len(contributors)
            contributions = {
                candidate['id']: contribution
                for candidate in contributors
            }
            for candidate in contributors[:unlock_rule['cost'] % len(contributors)]:
                contributions[candidate['id']] += 1
            deficits = [
                candidate for candidate in contributors
                if candidate['game']['money'] < contributions[candidate['id']]
            ]
            for underfunded in deficits:
                deficit = contributions[underfunded['id']] - underfunded['game']['money']
                contributions[underfunded['id']] -= deficit
                donor = next(
                    (
                        candidate for candidate in contributors
                        if candidate['id'] != underfunded['id']
                        and candidate['game']['money'] - contributions[candidate['id']] >= deficit
                    ),
                    None,
                )
                if donor is not None:
                    contributions[donor['id']] += deficit
            if all(
                contributions[candidate['id']] > 0
                and candidate['game']['money'] >= contributions[candidate['id']]
                for candidate in contributors
            ):
                return Decision(
                    action='PROPOSE_UNLOCK',
                    stage=next_stage,
                    contributions=contributions,
                    reason=f'Invest together to unlock Stage {next_stage}.',
                    message=f'I propose we pool gold to unlock Stage {next_stage}.',
                )
        for item_id in robot['game']['inventory']:
            quantity = inventory_quantity(robot, item_id)
            if quantity > 0 and valid_price(inventory_sell_price(world, robot, item_id)):
                return Decision(action='SELL', location='market', item=item_id,
                                quantity=quantity, reason='Sell inventory toward our shared gold goal.',
                                message=f'I’ll sell {quantity} {item_id} from my inventory while you keep collecting.')
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
        peer = next(
            (
                message for message in reversed(heard)
                if message.get('robot_id') != robot_id
            ),
            None,
        )
        message = 'I’ll fish while no crop is ready.'
        if peer and peer.get('action') == 'SELL':
            message = 'I’ll keep collecting at the lake while you sell.'
        return Decision(
            action='FISH',
            location='lake',
            message=message,
            reason='Collect fish while waiting for a ready farm plot.',
        )
