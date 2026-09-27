"""Runtime configuration for overhead vision and robot agents."""

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path


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


def load_navigation_config(path: str | Path) -> NavigationConfig:
    with open(path) as file:
        return NavigationConfig(**json.load(file))


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
    autonomy_enabled: bool = field(
        default_factory=lambda: environment_bool('AUTONOMY_ENABLED'),
    )
    autonomy_provider: str = field(
        default_factory=lambda: os.getenv('AUTONOMY_PROVIDER', 'mock'),
    )

    def __post_init__(self):
        self.game_mode = self.game_mode.strip().lower()
        self.autonomy_provider = self.autonomy_provider.strip().lower()
        if self.game_mode not in ('simulation', 'hardware'):
            raise ValueError('GAME_MODE must be either simulation or hardware')
        if type(self.autonomy_enabled) is not bool:
            raise ValueError('AUTONOMY_ENABLED must be true or false')
        if self.autonomy_provider not in ('mock', 'gemini'):
            raise ValueError('AUTONOMY_PROVIDER must be either mock or gemini')
        timeout_values = (
            self.health_timeout_seconds,
            self.pose_timeout_seconds,
            self.telemetry_check_interval_seconds,
        )
        if any(not math.isfinite(value) or value <= 0 for value in timeout_values):
            raise ValueError('Telemetry timeouts and check interval must be positive finite numbers')
