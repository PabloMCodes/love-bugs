"""Runtime configuration for overhead vision and robot agents."""

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


def environment_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ('1', 'true', 'yes', 'on'):
        return True
    if normalized in ('0', 'false', 'no', 'off'):
        return False
    raise ValueError(f'{name} must be true or false')


class GameConfigModel(BaseModel):
    """Strict base for the startup profile that seeds a new game session."""

    model_config = ConfigDict(extra='forbid')


class GameLocationConfig(GameConfigModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)


class GameMapConfig(GameConfigModel):
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    locations: dict[str, GameLocationConfig]

    @model_validator(mode='after')
    def validate_service_points(self):
        required = {'homebase', 'farm', 'lake', 'market'}
        missing = required - set(self.locations)
        if missing:
            raise ValueError(
                'map.locations is missing required service points: '
                + ', '.join(sorted(missing))
            )
        for name, location in self.locations.items():
            if location.x > self.width or location.y > self.height:
                raise ValueError(
                    f'map location {name!r} must be inside the configured map'
                )
        return self


class MarketItemConfig(GameConfigModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    buy_price: int = Field(ge=0)
    required_stage: int = Field(ge=1, le=3)
    unlock_at: int | None = Field(default=None, ge=0)


class CropConfig(GameConfigModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    seed_item_id: str = Field(min_length=1)
    grow_seconds: float = Field(gt=0)
    harvest_quantity: int = Field(ge=1)
    sell_price: int = Field(ge=0)
    required_stage: int = Field(ge=1, le=3)


class StageUnlockConfig(GameConfigModel):
    stage: int = Field(ge=2, le=3)
    item_id: str = Field(min_length=1)
    item_name: str = Field(min_length=1)
    eligibility_gold: int = Field(ge=0)
    cost: int = Field(ge=1)


class FishingTierConfig(GameConfigModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    sell_price: int = Field(ge=0)
    probability: float = Field(gt=0, le=1)


class FishingConfig(GameConfigModel):
    min_duration_seconds: float = Field(gt=0)
    max_duration_seconds: float = Field(gt=0)
    tiers: list[FishingTierConfig] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_fishing_rules(self):
        if self.max_duration_seconds < self.min_duration_seconds:
            raise ValueError('maximum fishing duration cannot be below the minimum')
        if abs(sum(tier.probability for tier in self.tiers) - 1) > 1e-9:
            raise ValueError('fishing tier probabilities must total 1')
        if len({tier.id for tier in self.tiers}) != len(self.tiers):
            raise ValueError('fishing tier IDs must be unique')
        return self


class GameProfile(GameConfigModel):
    """Validated, replaceable rules and service points for a new session."""

    profile_version: int = Field(default=1, ge=1)
    starting_gold_per_robot: int = Field(ge=0)
    victory_target: int = Field(ge=1)
    plot_count: int = Field(ge=1, le=20)
    map: GameMapConfig
    market_items: list[MarketItemConfig] = Field(min_length=1)
    crops: list[CropConfig] = Field(min_length=1)
    stage_unlocks: list[StageUnlockConfig]
    fishing: FishingConfig

    @model_validator(mode='after')
    def validate_progression(self):
        item_ids = [item.id for item in self.market_items]
        crop_ids = [crop.id for crop in self.crops]
        unlock_stages = [unlock.stage for unlock in self.stage_unlocks]
        if self.victory_target <= self.starting_gold_per_robot * 2:
            raise ValueError(
                'victory_target must exceed the two robots\' combined starting gold'
            )
        if len(set(item_ids)) != len(item_ids):
            raise ValueError('market item IDs must be unique')
        if len(set(crop_ids)) != len(crop_ids):
            raise ValueError('crop IDs must be unique')
        if len(set(unlock_stages)) != len(unlock_stages):
            raise ValueError('stage unlock rules must have unique stages')
        if set(unlock_stages) != {2, 3}:
            raise ValueError('stage unlock rules must define stages 2 and 3')
        if {item.required_stage for item in self.market_items} != {1, 2, 3}:
            raise ValueError('market items must cover farming stages 1, 2, and 3')
        if {crop.required_stage for crop in self.crops} != {1, 2, 3}:
            raise ValueError('crops must cover farming stages 1, 2, and 3')

        items = {item.id: item for item in self.market_items}
        if any(
            item.required_stage == 1 and item.unlock_at is not None
            for item in self.market_items
        ):
            raise ValueError('stage 1 market items cannot require an unlock threshold')
        for crop in self.crops:
            seed = items.get(crop.seed_item_id)
            if seed is None:
                raise ValueError(
                    f'crop {crop.id!r} references unknown seed {crop.seed_item_id!r}'
                )
            if seed.required_stage != crop.required_stage:
                raise ValueError(
                    f'crop {crop.id!r} and seed {seed.id!r} must use the same stage'
                )
        for unlock in self.stage_unlocks:
            item = items.get(unlock.item_id)
            if item is None or item.required_stage != unlock.stage:
                raise ValueError(
                    f'stage {unlock.stage} unlock must reference an item from that stage'
                )
            if item.name != unlock.item_name:
                raise ValueError('unlock item names must match market item names')
            if item.unlock_at != unlock.eligibility_gold:
                raise ValueError(
                    'market unlock_at must match the stage eligibility_gold'
                )
        return self


DEFAULT_GAME_PROFILE = {
    'profile_version': 1,
    'starting_gold_per_robot': 40,
    'victory_target': 200,
    'plot_count': 3,
    'map': {
        'width': 100,
        'height': 100,
        'locations': {
            'homebase': {'x': 50, 'y': 30},
            'farm': {'x': 20, 'y': 50},
            'lake': {'x': 12, 'y': 30},
            'market': {'x': 80, 'y': 25},
        },
    },
    'market_items': [
        {
            'id': 'seeds', 'name': 'Wheat Seeds', 'buy_price': 5,
            'required_stage': 1, 'unlock_at': None,
        },
        {
            'id': 'carrot_seeds', 'name': 'Carrot Seeds', 'buy_price': 10,
            'required_stage': 2, 'unlock_at': 100,
        },
        {
            'id': 'pumpkin_seeds', 'name': 'Pumpkin Seeds', 'buy_price': 20,
            'required_stage': 3, 'unlock_at': 150,
        },
    ],
    'crops': [
        {
            'id': 'wheat', 'name': 'Wheat', 'seed_item_id': 'seeds',
            'grow_seconds': 8, 'harvest_quantity': 3, 'sell_price': 12,
            'required_stage': 1,
        },
        {
            'id': 'carrot', 'name': 'Carrots', 'seed_item_id': 'carrot_seeds',
            'grow_seconds': 12, 'harvest_quantity': 3, 'sell_price': 20,
            'required_stage': 2,
        },
        {
            'id': 'pumpkin', 'name': 'Pumpkins', 'seed_item_id': 'pumpkin_seeds',
            'grow_seconds': 18, 'harvest_quantity': 3, 'sell_price': 32,
            'required_stage': 3,
        },
    ],
    'stage_unlocks': [
        {
            'stage': 2, 'item_id': 'carrot_seeds', 'item_name': 'Carrot Seeds',
            'eligibility_gold': 100, 'cost': 30,
        },
        {
            'stage': 3, 'item_id': 'pumpkin_seeds', 'item_name': 'Pumpkin Seeds',
            'eligibility_gold': 150, 'cost': 60,
        },
    ],
    'fishing': {
        'min_duration_seconds': 5,
        'max_duration_seconds': 15,
        'tiers': [
            {
                'id': 'common_fish', 'name': 'Common Fish',
                'sell_price': 1, 'probability': .70,
            },
            {
                'id': 'uncommon_fish', 'name': 'Uncommon Fish',
                'sell_price': 5, 'probability': .25,
            },
            {
                'id': 'rare_fish', 'name': 'Extremely Rare Fish',
                'sell_price': 15, 'probability': .05,
            },
        ],
    },
}


def default_game_profile() -> GameProfile:
    return GameProfile.model_validate(DEFAULT_GAME_PROFILE)


def load_game_profile(path: str | Path) -> GameProfile:
    with open(path) as file:
        return GameProfile.model_validate(json.load(file))


@dataclass(frozen=True)
class Zone:
    name: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self):
        if not (0 <= self.x_min < self.x_max <= 1 and
                0 <= self.y_min < self.y_max <= 1):
            raise ValueError(f"Invalid normalized rectangle for zone {self.name!r}")

    def contains(self, x: float, y: float) -> bool:
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max


@dataclass(frozen=True)
class VisionConfig:
    marker_to_robot: dict[int, str]
    zones: tuple[Zone, ...]


@dataclass(frozen=True)
class NavigationConfig:
    camera_index: int = 0
    marker_id: int = 0
    target_x: float = 500
    target_y: float = 300
    heading_offset_degrees: float = 0
    invert_turns: bool = False
    stop_distance: float = 35
    angle_threshold: float = 15
    command_hz: float = 10
    refresh_seconds: float = .3
    marker_timeout: float = .5
    pulse_seconds: float = .12
    pause_seconds: float = .3
    ble_device: str = ''
    ble_characteristic: str = ''
    ble_write_response: bool = True
    ble_direct_address: bool = False

    def __post_init__(self):
        if type(self.marker_id) is not int or not 0 <= self.marker_id < 50:
            raise ValueError('marker_id must be 0–49 (DICT_4X4_50)')
        if type(self.camera_index) is not int or self.camera_index < 0:
            raise ValueError('camera_index must be a nonnegative integer')
        for name in ('stop_distance', 'angle_threshold', 'command_hz', 'refresh_seconds',
                     'marker_timeout', 'pulse_seconds', 'pause_seconds'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be positive and finite')
        if not 5 <= self.command_hz <= 10 or self.angle_threshold >= 180:
            raise ValueError('command_hz must be 5–10; angle_threshold must be below 180')
        if self.marker_timeout > .5:
            raise ValueError('marker_timeout must be at most 0.5 seconds')
        if min(self.pulse_seconds, self.pause_seconds, self.refresh_seconds) < 1 / self.command_hz:
            raise ValueError('Pulse, pause and refresh must be at least one command period')
        if any(not math.isfinite(v) for v in
               (self.target_x, self.target_y, self.heading_offset_degrees)):
            raise ValueError('Target and heading offset must be finite')
        if min(self.target_x, self.target_y) < 0:
            raise ValueError('Target coordinates must be nonnegative')
        if type(self.invert_turns) is not bool or type(self.ble_write_response) is not bool:
            raise ValueError('Turn inversion and BLE response settings must be booleans')
        if type(self.ble_direct_address) is not bool:
            raise ValueError('ble_direct_address must be a boolean')


def load_navigation_config(path: str | Path) -> NavigationConfig:
    with open(path) as file:
        return NavigationConfig(**json.load(file))


@dataclass(frozen=True)
class NavigationRobot:
    robot_id: str
    name: str
    config: NavigationConfig


def load_navigation_robots(path: str | Path) -> tuple[NavigationRobot, ...]:
    """Two independent profiles; the existing single-robot config is unchanged."""
    with open(path) as file:
        data = json.load(file)
    if set(data) != {'robot-a', 'robot-b'}:
        raise ValueError('Two-robot configuration requires robot-a and robot-b')
    robots = []
    for robot_id in ('robot-a', 'robot-b'):
        values = dict(data[robot_id])
        name = values.pop('name')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Each robot needs a display name')
        robots.append(NavigationRobot(robot_id, name, NavigationConfig(**values)))
    if robots[0].config.marker_id == robots[1].config.marker_id:
        raise ValueError('Robots must have different ArUco marker IDs')
    devices = [r.config.ble_device.strip().casefold() for r in robots]
    if not all(devices) or len(set(devices)) != 2:
        raise ValueError('Robots must have distinct, nonempty BLE devices')
    if robots[0].config.camera_index != robots[1].config.camera_index:
        raise ValueError('Both robots must use the same overhead camera')
    return tuple(robots)


def load_vision_config(path: str | Path) -> VisionConfig:
    with open(path) as file:
        data = json.load(file)
    mapping = {int(key): value for key, value in data['marker_to_robot'].items()}
    if any(not 0 <= key < 50 for key in mapping):
        raise ValueError('Marker IDs must be in DICT_4X4_50 range 0–49')
    if any(not isinstance(value, str) or not value.strip() for value in mapping.values()):
        raise ValueError('Robot IDs must be nonempty strings')
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('Each robot must have a unique marker')
    zones = tuple(Zone(name=name, **bounds) for name, bounds in data['zones'].items())
    return VisionConfig(mapping, zones)


@dataclass(frozen=True)
class AgentConfig:
    model: str = 'gemini-3.5-flash-lite'
    interval_seconds: float = 10
    timeout_seconds: float = 20

    @classmethod
    def from_env(cls):
        import os
        import math

        config = cls(
            model=os.getenv('AGENT_MODEL', 'gemini-3.5-flash-lite'),
            interval_seconds=float(os.getenv('AGENT_INTERVAL_SECONDS', '10')),
            timeout_seconds=float(os.getenv('AGENT_TIMEOUT_SECONDS', '20')),
        )
        if not config.model.strip() or any(
            not math.isfinite(value) or value <= 0
            for value in (config.interval_seconds, config.timeout_seconds)
        ):
            raise ValueError('Agent model must be nonempty; interval and timeout must be positive finite numbers')
        return config


@dataclass
class Settings:
    database_url: str | None = field(default_factory=lambda: os.getenv("DATABASE_URL") or None)
    sqlite_path: str = field(default_factory=lambda: os.getenv("SQLITE_PATH", "./lovebugs.sqlite3"))
    game_mode: str = field(default_factory=lambda: os.getenv('GAME_MODE', 'simulation'))
    health_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv('HEALTH_TIMEOUT_SECONDS', '5')),
    )
    pose_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv('POSE_TIMEOUT_SECONDS', '2')),
    )
    telemetry_check_interval_seconds: float = field(
        default_factory=lambda: float(os.getenv('TELEMETRY_CHECK_INTERVAL_SECONDS', '.25')),
    )
    economy_request_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv('ECONOMY_REQUEST_TIMEOUT_SECONDS', '30')),
    )
    autonomy_enabled: bool = field(
        default_factory=lambda: environment_bool('AUTONOMY_ENABLED'),
    )
    autonomy_provider: str = field(
        default_factory=lambda: os.getenv('AUTONOMY_PROVIDER', 'mock'),
    )
    fishing_random_seed: int | None = field(
        default_factory=lambda: (
            int(os.environ['FISHING_RANDOM_SEED'])
            if os.getenv('FISHING_RANDOM_SEED') not in (None, '')
            else None
        ),
    )
    game_config_path: str | None = field(
        default_factory=lambda: os.getenv('GAME_CONFIG_PATH') or None,
    )
    game_profile: GameProfile = field(init=False, repr=False)

    def __post_init__(self):
        self.game_mode = self.game_mode.strip().lower()
        self.autonomy_provider = self.autonomy_provider.strip().lower()
        if self.game_mode not in ('simulation', 'hardware'):
            raise ValueError('GAME_MODE must be either simulation or hardware')
        if type(self.autonomy_enabled) is not bool:
            raise ValueError('AUTONOMY_ENABLED must be true or false')
        if self.autonomy_provider not in ('mock', 'gemini'):
            raise ValueError('AUTONOMY_PROVIDER must be either mock or gemini')
        if self.fishing_random_seed is not None and type(self.fishing_random_seed) is not int:
            raise ValueError('FISHING_RANDOM_SEED must be an integer')
        timeout_values = (
            self.health_timeout_seconds,
            self.pose_timeout_seconds,
            self.telemetry_check_interval_seconds,
            self.economy_request_timeout_seconds,
        )
        if any(not math.isfinite(value) or value <= 0 for value in timeout_values):
            raise ValueError(
                'Telemetry and economy timeouts and check intervals must be positive finite numbers'
            )
        self.game_profile = (
            load_game_profile(self.game_config_path)
            if self.game_config_path is not None
            else default_game_profile()
        )
