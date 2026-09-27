"""Validation and mutation helpers for execution-time market transactions."""

from dataclasses import dataclass


class MarketRuleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SellQuote:
    item_id: str
    item_name: str
    quantity: int
    unit_price: int

    @property
    def earnings(self) -> int:
        return self.quantity * self.unit_price


@dataclass(frozen=True)
class BuyQuote:
    item_id: str
    item_name: str
    quantity: int
    unit_price: int
    sell_price: int | None

    @property
    def cost(self) -> int:
        return self.quantity * self.unit_price


def trade_parameters(parameters: dict, action: str) -> tuple[str, int]:
    if set(parameters) != {'item', 'quantity'}:
        raise MarketRuleError(
            'INVALID_REQUEST',
            f'{action} requires only item and quantity parameters.',
        )

    item_id = parameters['item']
    quantity = parameters['quantity']
    if not isinstance(item_id, str) or not item_id:
        raise MarketRuleError(
            'INVALID_REQUEST',
            f'{action} item must be a nonempty string.',
        )
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise MarketRuleError(
            'INVALID_REQUEST',
            f'{action} quantity must be a positive integer.',
        )

    return item_id, quantity


def quote_purchase(
    game: dict,
    market: dict,
    parameters: dict,
    *,
    current_stage: int = 1,
) -> BuyQuote:
    item_id, quantity = trade_parameters(parameters, 'BUY')
    item = next(
        (candidate for candidate in market['items'] if candidate['id'] == item_id),
        None,
    )
    if item is None:
        raise MarketRuleError('NOT_FOUND', f'Unknown market item {item_id}.')
    if item['buy_price'] is None:
        raise MarketRuleError('INVALID_REQUEST', f'{item_id} cannot be purchased.')
    if current_stage < item.get('required_stage', 1):
        raise MarketRuleError(
            'SEED_LOCKED',
            f"{item['name']} unlock at farming stage {item['required_stage']}.",
        )

    quote = BuyQuote(
        item_id=item_id,
        item_name=item['name'],
        quantity=quantity,
        unit_price=item['buy_price'],
        sell_price=item.get('sell_price'),
    )
    if game['money'] < quote.cost:
        raise MarketRuleError('INSUFFICIENT_FUNDS', 'The robot does not have enough gold.')
    if item['stock'] is not None and item['stock'] < quantity:
        raise MarketRuleError('OUT_OF_STOCK', f'Not enough {item_id} is in stock.')

    return quote


def apply_purchase(
    game: dict,
    market: dict,
    parameters: dict,
    *,
    current_stage: int = 1,
) -> BuyQuote:
    quote = quote_purchase(
        game,
        market,
        parameters,
        current_stage=current_stage,
    )
    market_item = next(
        item for item in market['items'] if item['id'] == quote.item_id
    )
    inventory_item = game['inventory'].get(quote.item_id)

    if inventory_item is None:
        game['inventory'][quote.item_id] = {
            'name': quote.item_name,
            'quantity': quote.quantity,
            'sell_price': quote.sell_price,
        }
    else:
        inventory_item['quantity'] += quote.quantity

    if market_item['stock'] is not None:
        market_item['stock'] -= quote.quantity
    game['money'] -= quote.cost
    return quote


def quote_sale(game: dict, parameters: dict) -> SellQuote:
    item_id, quantity = trade_parameters(parameters, 'SELL')

    item = game['inventory'].get(item_id)
    if item is None or item['quantity'] < quantity:
        raise MarketRuleError(
            'INSUFFICIENT_INVENTORY',
            f'Not enough {item_id} is available to sell.',
        )
    if item['sell_price'] is None:
        raise MarketRuleError('INVALID_REQUEST', f'{item_id} cannot be sold.')

    return SellQuote(
        item_id=item_id,
        item_name=item['name'],
        quantity=quantity,
        unit_price=item['sell_price'],
    )


def apply_sale(game: dict, parameters: dict) -> SellQuote:
    quote = quote_sale(game, parameters)
    item = game['inventory'][quote.item_id]
    remaining = item['quantity'] - quote.quantity

    if remaining == 0:
        del game['inventory'][quote.item_id]
    else:
        item['quantity'] = remaining

    game['money'] += quote.earnings
    return quote
