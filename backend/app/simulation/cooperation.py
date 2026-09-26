"""Manual simulation clock and single-process transaction orchestration.

Only this adapter supplies simulated poses. Game rules receive structured reports
and agent proposals, so a future hardware/agent adapter can use the same validators.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.agents.planner import DeterministicOrderAgent
from app.agents.protocol import AgentContext, RobotAgent
from app.game.cooperation import ArrivalReport, OrderRules, require
from app.schemas import Pose, PositionSample
from app.simulation.simulator import seed_session


class SimulationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    expected_revision: int = Field(ge=0, strict=True)


class CooperationDemo:
    def __init__(self, store, session_id, agents: dict[str, RobotAgent] | None = None):
        self.store, self.session_id = store, session_id
        self.lock = RLock()
        self.agents = agents if agents is not None else {
            rid: DeterministicOrderAgent(rid) for rid in ("robot-a", "robot-b")}

    def snapshot(self):
        with self.lock:
            return {"world": self.store.world(self.session_id),
                    "objective": self.store.objective(self.session_id), "policy": "deterministic"}

    def execute(self, operation, command: SimulationCommand):
        with self.lock:
            world = self.store.world(self.session_id)
            require(command.session_id == self.session_id, "Session changed; reload the current world.")
            require(command.expected_revision == world["revision"], "Revision changed; reload before advancing.")
            require(world["mode"] == "simulation", "Simulation controls cannot operate hardware.")
            if operation == "reset":
                # No background movement exists; replacing the active session invalidates
                # every old action/report. Old session data remains historical.
                self.session_id = seed_session(self.store, reset=True)
                return self.snapshot()
            objective = self.store.objective(self.session_id)
            now = max(datetime.now(timezone.utc),
                      datetime.fromisoformat(world["updated_at"]) + timedelta(milliseconds=1))
            if operation == "start":
                require(objective is None and world["game"]["status"] == "READY", "Reset before starting another scenario.")
                objective = {"id": str(uuid4()), "phase": "ASSIGNED", "arrived": [],
                             "messages": [], "tasks": [], "forgone_sale_value": None,
                             "requirements": {"wheat": 1, "fish": 1}, "reward_gold": 10,
                             "reward_split": {"robot-a": 5, "robot-b": 5}}
                rules = OrderRules(world, objective, now)
                world["game"]["status"] = "RUNNING"
                rules.emit("scenario_started", "A new order from you: bring one wheat and one fish Home! Billy and Milo can earn 10 gold together.",
                           policy="deterministic", issued_by="human", requirements=objective["requirements"],
                           reward_gold=objective["reward_gold"], reward_split=objective["reward_split"])
                for r, location, item, action, reason in (
                    (world["robots"][0], "farm", "wheat", "FULFILL_ORDER", "Billy will bring his wheat Home to fulfill your order. He still needs a fish from a partner."),
                    (world["robots"][1], "lake", "fish", "SELL", "Milo has a fish and plans a little market trip to sell it."),
                ):
                    r["game"].update(location=location, inventory={item: 1})
                    pose = Pose(**world["map"]["locations"][location], heading=0)
                    r["physical"].update(pose=pose.model_dump(), pose_updated_at=now.isoformat(), online=False)
                    rules.positions.append(PositionSample(session_id=self.session_id, robot_id=r["id"],
                                                          timestamp=now, source="simulation", pose=pose))
                    rules.emit("inventory_updated", f'Simulation setup: {r["name"]} has one {item}.',
                               r["id"], item=item, quantity=1, source="simulation")
                    rules.assign(r["id"], action, reason)
            else:
                require(objective is not None, "Start the scenario first.")
                require(world["game"]["status"] == "RUNNING", "Game is not running.")
                rules = OrderRules(world, objective, now)
                phase = objective["phase"]
                if phase in ("ASSIGNED", "HELP_REQUESTED"):
                    rid = "robot-a" if phase == "ASSIGNED" else "robot-b"
                    context = AgentContext(rid, deepcopy(world), deepcopy(objective),
                                           deepcopy([m for m in objective["messages"] if m["recipient_id"] == rid]))
                    proposal = self.agents[rid].propose(context)
                    require(proposal is not None and proposal.robot_id == rid, "Agent did not propose a valid action.")
                    rules.apply_action(proposal)
                elif phase == "HELP_ACCEPTED":
                    rules.depart()
                    # A visible intermediate position; arrival is a separate validated step.
                    home = world["map"]["locations"]["homebase"]
                    for r in world["robots"]:
                        current = r["physical"]["pose"]
                        pose = Pose(x=(current["x"] + home["x"]) / 2,
                                    y=(current["y"] + home["y"]) / 2, heading=current["heading"])
                        r["physical"].update(pose=pose.model_dump(), pose_updated_at=now.isoformat())
                        rules.positions.append(PositionSample(session_id=self.session_id, robot_id=r["id"],
                                                              timestamp=now, source="simulation", pose=pose))
                elif phase in ("TRAVELING_HOME", "ONE_ARRIVED"):
                    rid = next(r for r in ("robot-a", "robot-b") if r not in objective["arrived"])
                    r = next(r for r in world["robots"] if r["id"] == rid)
                    sample = PositionSample(session_id=self.session_id, robot_id=rid, timestamp=now,
                                            source="simulation", pose=Pose(**world["map"]["locations"]["homebase"], heading=0))
                    rules.arrive(ArrivalReport(session_id=self.session_id, robot_id=rid,
                                              task_id=r["task"]["id"], location="homebase", sample=sample))
                elif phase == "BOTH_ARRIVED":
                    rules.share_and_complete()
                else:
                    require(False, "Scenario is complete; reset to replay.")
            world["revision"] += 1
            world["updated_at"] = (rules.events[-1].timestamp if rules.events else now).isoformat()
            self.store.commit(world, rules.events, rules.positions, objective=objective)
            return self.snapshot()
