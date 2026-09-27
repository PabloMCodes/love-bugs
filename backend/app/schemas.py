"""Validated models for the canonical world snapshot."""

from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Goal(StrictModel):
    type: Literal['earn_gold'] = 'earn_gold'
    target: int = Field(ge=1)
    current: int = Field(ge=0)


class GoalRequest(StrictModel):
    type: Literal['earn_gold']
    target: int = Field(ge=1)


class GameState(StrictModel):
    status: Literal['READY', 'RUNNING', 'STOPPED', 'COMPLETED']
    goal: Goal
    stage: int = Field(default=1, ge=1, le=3)


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


class PoseReport(StrictModel):
    session_id: str = Field(min_length=1, max_length=100)
    pose: Pose
    timestamp: AwareDatetime


class HealthReport(StrictModel):
    session_id: str = Field(min_length=1, max_length=100)
    online: bool
    battery: float | None = Field(default=None, ge=0, le=1)
    blocked: bool


class ArrivalReport(StrictModel):
    session_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=100)


class BlockedReport(StrictModel):
    session_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=300)
    duration_ms: int = Field(ge=0)


class AcceptedResponse(StrictModel):
    accepted: bool


class Robot(StrictModel):
    id: str
    name: str
    physical: PhysicalState
    game: RobotGameState
    task: RobotTask | None


class RobotsResponse(StrictModel):
    robots: list[Robot]


class TasksResponse(StrictModel):
    tasks: list[RobotTask]


class MarketItem(StrictModel):
    id: str
    name: str
    buy_price: int | None = Field(default=None, ge=0)
    sell_price: int | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0)
    required_stage: int = Field(default=1, ge=1, le=3)
    unlock_at: int | None = Field(default=None, ge=0)


class Market(StrictModel):
    items: list[MarketItem]


class CropDefinition(StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    seed_item_id: str = Field(min_length=1)
    grow_seconds: float = Field(gt=0)
    harvest_quantity: int = Field(ge=1)
    sell_price: int = Field(ge=0)
    required_stage: int = Field(default=1, ge=1, le=3)


class FarmPlot(StrictModel):
    id: str = Field(min_length=1)
    status: Literal['EMPTY', 'GROWING', 'READY']
    crop_id: str | None = None
    planted_by: str | None = None
    planted_at: AwareDatetime | None = None
    ready_at: AwareDatetime | None = None

    @model_validator(mode='after')
    def validate_crop_state(self):
        crop_fields = (
            self.crop_id,
            self.planted_by,
            self.planted_at,
            self.ready_at,
        )
        if self.status == 'EMPTY' and any(value is not None for value in crop_fields):
            raise ValueError('empty plots cannot contain crop state')
        if self.status != 'EMPTY' and any(value is None for value in crop_fields):
            raise ValueError('growing and ready plots require complete crop state')
        if (
            self.planted_at is not None
            and self.ready_at is not None
            and self.ready_at <= self.planted_at
        ):
            raise ValueError('ready_at must be later than planted_at')
        return self


class Farm(StrictModel):
    crops: list[CropDefinition]
    plots: list[FarmPlot]


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
    farm: Farm
    events: list[WorldEvent]
