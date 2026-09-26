"""Runtime configuration for overhead vision and robot agents."""

import json
from dataclasses import dataclass
from pathlib import Path


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
