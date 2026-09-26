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


def quote_sale(game: dict, parameters: dict) -> SellQuote:
    if set(parameters) != {'item', 'quantity'}:
        raise MarketRuleError(
            'INVALID_REQUEST',
            'SELL requires only item and quantity parameters.',
        )

    item_id = parameters['item']
    quantity = parameters['quantity']
    if not isinstance(item_id, str) or not item_id:
        raise MarketRuleError('INVALID_REQUEST', 'SELL item must be a nonempty string.')
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise MarketRuleError('INVALID_REQUEST', 'SELL quantity must be a positive integer.')

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
