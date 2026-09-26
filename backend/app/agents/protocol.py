"""Robot agent boundary. Proposals never mutate state or send motor commands."""
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class AgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    objective_id: str
    robot_id: str
    action: Literal["REQUEST_HELP", "HELP_PARTNER"]
    request_id: str
    reason: str = Field(min_length=1, max_length=300)


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    objective_id: str
    request_id: str
    sender_id: str
    recipient_id: str
    type: Literal["HELP_REQUESTED", "HELP_ACCEPTED"]
    item: Literal["fish"] = "fish"
    quantity: Literal[1] = 1
    reason: str


@dataclass(frozen=True)
class AgentContext:
    robot_id: str
    world: dict
    objective: dict
    inbox: list[dict]


class RobotAgent(Protocol):
    def propose(self, context: AgentContext) -> AgentAction | None: ...
