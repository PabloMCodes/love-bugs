"""Validated models for the canonical world snapshot."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Goal(StrictModel):
    type: Literal['earn_gold'] = 'earn_gold'
    target: int = Field(ge=1)
    current: int = Field(ge=0)


class GameState(StrictModel):
    status: Literal['READY', 'RUNNING', 'STOPPED', 'COMPLETED']
    goal: Goal


class Point(StrictModel):
    x: float
    y: float


class Pose(Point):
    heading: float = Field(ge=0, lt=360)


class WorldMap(StrictModel):
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    locations: dict[str, Point]


class PhysicalState(StrictModel):
    online: bool
    pose: Pose | None
    pose_updated_at: datetime | None
    tracking: Literal['TRACKED', 'STALE', 'UNKNOWN']
    battery: float | None = Field(default=None, ge=0, le=1)
    blocked: bool
    stopped: bool


class InventoryItem(StrictModel):
    name: str = Field(min_length=1)
    quantity: int = Field(ge=0)
    sell_price: int | None = Field(default=None, ge=0)


class RobotGameState(StrictModel):
    location: str | None
    money: int = Field(ge=0)
    inventory: dict[str, InventoryItem]


class TaskError(StrictModel):
    code: str
    message: str


class RobotTask(StrictModel):
    id: str
    robot_id: str
    action: Literal['MOVE_TO', 'HARVEST', 'FISH', 'BUY', 'SELL', 'RETURN_HOME']
    location: str
    status: Literal[
        'ASSIGNED',
        'NAVIGATING',
        'ACTIVE',
        'COMPLETED',
        'FAILED',
        'CANCELLED',
    ]
    progress: float = Field(ge=0, le=1)
    parameters: dict[str, Any]
    reason: str | None
    error: TaskError | None


class TaskRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=100)
    robot_id: str = Field(min_length=1, max_length=100)
    action: Literal['MOVE_TO', 'HARVEST', 'FISH', 'BUY', 'SELL', 'RETURN_HOME']
    location: str = Field(min_length=1, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=300)


class NavigationStep(StrictModel):
    robot_id: str
    task_id: str
    pose: Pose
    location: str
    arrived: bool


class Robot(StrictModel):
    id: str
    name: str
    physical: PhysicalState
    game: RobotGameState
    task: RobotTask | None


class MarketItem(StrictModel):
    id: str
    name: str
    buy_price: int | None = Field(default=None, ge=0)
    sell_price: int | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0)


class Market(StrictModel):
    items: list[MarketItem]


class WorldEvent(StrictModel):
    id: str
    timestamp: datetime
    type: str
    robot_id: str | None
    task_id: str | None
    message: str
    data: dict[str, Any]


class WorldSnapshot(StrictModel):
    schema_version: int = Field(ge=1)
    session_id: str
    revision: int = Field(ge=0)
    updated_at: datetime
    mode: Literal['simulation', 'hardware']
    game: GameState
    map: WorldMap
    robots: list[Robot]
    market: Market
    events: list[WorldEvent]
