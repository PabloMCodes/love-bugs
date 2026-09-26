"""History records shared by simulation and future validated hardware adapters."""
from typing import Any
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Pose(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    heading: float = Field(ge=0, lt=360)


class PositionSample(BaseModel):
    session_id: str
    robot_id: str
    timestamp: AwareDatetime
    source: str  # simulation or an identified localization adapter
    pose: Pose


class Event(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: AwareDatetime
    type: str
    robot_id: str | None = None
    task_id: str | None = None
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
