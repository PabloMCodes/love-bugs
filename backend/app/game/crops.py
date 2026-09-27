"""Validation and mutation helpers for authoritative planting and harvesting."""

from dataclasses import dataclass
from datetime import datetime, timedelta


class CropRuleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PlantingQuote:
    seed_item_id: str
    seed_name: str
    crop_id: str
    crop_name: str
    plot_id: str
    grow_seconds: float


@dataclass(frozen=True)
class HarvestQuote:
    plot_id: str
    crop_id: str
    crop_name: str
    quantity: int
    sell_price: int


def planting_parameters(parameters: dict) -> tuple[str, str]:
    if set(parameters) != {'item', 'plot_id'}:
        raise CropRuleError(
            'INVALID_REQUEST',
            'PLANT requires only item and plot_id parameters.',
        )

    item_id = parameters['item']
    plot_id = parameters['plot_id']
    if not isinstance(item_id, str) or not item_id:
        raise CropRuleError(
            'INVALID_REQUEST',
            'PLANT item must be a nonempty string.',
        )
    if not isinstance(plot_id, str) or not plot_id:
        raise CropRuleError(
            'INVALID_REQUEST',
            'PLANT plot_id must be a nonempty string.',
        )
    return item_id, plot_id


def quote_planting(
    game: dict,
    farm: dict,
    parameters: dict,
    *,
    current_stage: int = 1,
) -> PlantingQuote:
    item_id, plot_id = planting_parameters(parameters)
    crop = next(
        (candidate for candidate in farm['crops'] if candidate['seed_item_id'] == item_id),
        None,
    )
    if crop is None:
        raise CropRuleError('NOT_FOUND', f'Unknown seed item {item_id}.')
    if current_stage < crop.get('required_stage', 1):
        raise CropRuleError(
            'SEED_LOCKED',
            f"{crop['name']} unlocks at farming stage {crop['required_stage']}.",
        )

    inventory_item = game['inventory'].get(item_id)
    if inventory_item is None or inventory_item['quantity'] < 1:
        raise CropRuleError(
            'INSUFFICIENT_INVENTORY',
            f'One {item_id} is required to plant this crop.',
        )

    plot = next(
        (candidate for candidate in farm['plots'] if candidate['id'] == plot_id),
        None,
    )
    if plot is None:
        raise CropRuleError('NOT_FOUND', f'Unknown farm plot {plot_id}.')
    if plot['status'] != 'EMPTY':
        raise CropRuleError('PLOT_OCCUPIED', f'Farm plot {plot_id} is not empty.')

    return PlantingQuote(
        seed_item_id=item_id,
        seed_name=inventory_item['name'],
        crop_id=crop['id'],
        crop_name=crop['name'],
        plot_id=plot_id,
        grow_seconds=crop['grow_seconds'],
    )


def apply_planting(
    game: dict,
    farm: dict,
    parameters: dict,
    *,
    current_stage: int,
    planted_by: str,
    planted_at: datetime,
) -> PlantingQuote:
    quote = quote_planting(
        game,
        farm,
        parameters,
        current_stage=current_stage,
    )

    inventory_item = game['inventory'][quote.seed_item_id]
    remaining = inventory_item['quantity'] - 1
    if remaining == 0:
        del game['inventory'][quote.seed_item_id]
    else:
        inventory_item['quantity'] = remaining

    plot = next(
        candidate for candidate in farm['plots'] if candidate['id'] == quote.plot_id
    )
    plot.update({
        'status': 'GROWING',
        'crop_id': quote.crop_id,
        'planted_by': planted_by,
        'planted_at': planted_at,
        'ready_at': planted_at + timedelta(seconds=quote.grow_seconds),
    })
    return quote


def harvest_parameters(parameters: dict) -> str:
    if set(parameters) != {'plot_id'}:
        raise CropRuleError(
            'INVALID_REQUEST',
            'HARVEST requires only a plot_id parameter.',
        )
    plot_id = parameters['plot_id']
    if not isinstance(plot_id, str) or not plot_id:
        raise CropRuleError(
            'INVALID_REQUEST',
            'HARVEST plot_id must be a nonempty string.',
        )
    return plot_id


def quote_harvest(farm: dict, parameters: dict) -> HarvestQuote:
    plot_id = harvest_parameters(parameters)
    plot = next(
        (candidate for candidate in farm['plots'] if candidate['id'] == plot_id),
        None,
    )
    if plot is None:
        raise CropRuleError('NOT_FOUND', f'Unknown farm plot {plot_id}.')
    if plot['status'] != 'READY':
        raise CropRuleError(
            'PLOT_NOT_READY',
            f'Farm plot {plot_id} is not ready to harvest.',
        )

    crop = next(
        (candidate for candidate in farm['crops'] if candidate['id'] == plot['crop_id']),
        None,
    )
    if crop is None:
        raise CropRuleError('NOT_FOUND', f"Unknown crop {plot['crop_id']}.")

    return HarvestQuote(
        plot_id=plot_id,
        crop_id=crop['id'],
        crop_name=crop['name'],
        quantity=crop['harvest_quantity'],
        sell_price=crop['sell_price'],
    )


def apply_harvest(game: dict, farm: dict, parameters: dict) -> HarvestQuote:
    quote = quote_harvest(farm, parameters)
    inventory_item = game['inventory'].get(quote.crop_id)
    total_quantity = (
        inventory_item['quantity'] if inventory_item is not None else 0
    ) + quote.quantity
    game['inventory'][quote.crop_id] = {
        'name': (
            inventory_item['name']
            if inventory_item is not None
            else quote.crop_name
        ),
        'quantity': total_quantity,
        'sell_price': (
            inventory_item['sell_price']
            if inventory_item is not None
            else quote.sell_price
        ),
    }

    plot = next(
        candidate for candidate in farm['plots'] if candidate['id'] == quote.plot_id
    )
    plot.update({
        'status': 'EMPTY',
        'crop_id': None,
        'planted_by': None,
        'planted_at': None,
        'ready_at': None,
    })
    return quote
