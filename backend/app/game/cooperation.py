"""Deterministic shared-order rules shared by future agent and arrival adapters.

Functions mutate only the supplied working copy. The service validates and commits
that copy with its events, or discards it entirely on failure.
"""
from datetime import datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel

from app.agents.protocol import AgentAction, AgentMessage
from app.schemas import Event, PositionSample


class RuleViolation(Exception):
    pass


class ArrivalReport(BaseModel):
    session_id: str
    robot_id: str
    task_id: str
    location: str
    sample: PositionSample


def require(condition, reason):
    if not condition:
        raise RuleViolation(reason)


def robot(world, robot_id):
    return next(r for r in world["robots"] if r["id"] == robot_id)


class OrderRules:
    def __init__(self, world, objective, now):
        self.world, self.objective, self.now = world, objective, now
        self.events = []
        self.positions = []

    def emit(self, kind, reason, robot_id=None, **data):
        task = robot(self.world, robot_id)["task"] if robot_id else None
        self.events.append(Event(timestamp=self.now + timedelta(microseconds=len(self.events)),
                                 type=kind, robot_id=robot_id,
                                 task_id=task["id"] if task else None, message=reason,
                                 data={"objective_id": self.objective["id"], "reason": reason, **data}))

    def assign(self, robot_id, action, reason):
        task = {"id": str(uuid4()), "robot_id": robot_id, "action": action,
                "location": "market" if action == "SELL" else "homebase",
                "status": "ASSIGNED", "progress": 0, "parameters": {"objective_id": self.objective["id"]},
                "reason": reason, "error": None}
        if action == "SELL":
            task["parameters"].update(item="fish", quantity=1)
        robot(self.world, robot_id)["task"] = task
        self.objective["tasks"].append(task)
        self.emit("task_assigned", reason, robot_id, action=action)

    def sync_task(self, robot_id):
        task = robot(self.world, robot_id)["task"]
        for i, old in enumerate(self.objective["tasks"]):
            if old["id"] == task["id"]:
                self.objective["tasks"][i] = task.copy()

    def apply_action(self, action: AgentAction):
        o = self.objective
        require(action.session_id == self.world["session_id"] and action.objective_id == o["id"],
                "Action belongs to a different session or objective.")
        require(self.world["game"]["status"] == "RUNNING", "Game is not running.")
        if action.action == "REQUEST_HELP":
            require(action.robot_id == "robot-a" and o["phase"] == "ASSIGNED", "Help request is not available.")
            inv = robot(self.world, "robot-a")["game"]["inventory"]
            require(inv.get("wheat", 0) >= 1 and inv.get("fish", 0) == 0, "The order does not need Billy to request fish.")
            o["phase"] = "HELP_REQUESTED"
            kind, recipient = "HELP_REQUESTED", "robot-b"
        else:
            require(action.robot_id == "robot-b" and o["phase"] == "HELP_REQUESTED", "Help acceptance is not available.")
            require(any(m["type"] == "HELP_REQUESTED" and m["request_id"] == action.request_id
                        and m["sender_id"] == "robot-a" and m["recipient_id"] == "robot-b"
                        for m in o["messages"]), "No matching help request.")
            milo = robot(self.world, "robot-b")
            require(milo["game"]["inventory"].get("fish", 0) >= 1, "Milo has no fish to share.")
            require(milo["task"] and milo["task"]["action"] == "SELL", "Milo has no sale to give up.")
            price = next(i["sell_price"] for i in self.world["market"]["items"] if i["id"] == "fish")
            require(price is not None and price >= 0, "Fish sale value is unavailable.")
            o["forgone_sale_value"] = price
            self.emit("agent_decision", f"Milo chooses HELP_PARTNER: our order comes first! He passes up a possible {price} gold sale to bring Billy a fish.",
                      "robot-b", action="HELP_PARTNER", forgone_sale_value=price, policy="deterministic")
            milo["task"]["status"] = "CANCELLED"
            self.sync_task("robot-b")
            self.emit("task_cancelled", "Milo sets his market trip aside. The fish is for our order; no sale gold changes hands.", "robot-b")
            self.assign("robot-b", "HELP_PARTNER", action.reason)
            o["phase"] = "HELP_ACCEPTED"
            kind, recipient = "HELP_ACCEPTED", "robot-a"
        message = AgentMessage(session_id=action.session_id, objective_id=o["id"],
                               request_id=action.request_id, sender_id=action.robot_id,
                               recipient_id=recipient, type=kind, reason=action.reason)
        o["messages"].append(message.model_dump())
        self.emit(kind.lower(), action.reason, action.robot_id, agent_message=message.model_dump())

    def depart(self):
        require(self.objective["phase"] == "HELP_ACCEPTED", "Help must be accepted before travel.")
        home = self.world["map"]["locations"]["homebase"]
        for r in self.world["robots"]:
            require(not r["physical"]["stopped"] and not r["physical"]["blocked"], "Robot cannot travel.")
            r["task"]["status"] = "NAVIGATING"
            r["game"]["location"] = None
            self.sync_task(r["id"])
            self.emit("traveling_home", f'{r["name"]} heads Home with their contribution. Time to bring our order together!', r["id"],
                      destination="homebase", target=home)
        self.objective["phase"] = "TRAVELING_HOME"

    def arrive(self, report: ArrivalReport):
        require(self.world["game"]["status"] == "RUNNING" and self.objective["phase"] in
                {"TRAVELING_HOME", "ONE_ARRIVED", "BOTH_ARRIVED"}, "No active rendezvous.")
        require(report.session_id == self.world["session_id"], "Arrival belongs to an old session.")
        require(report.robot_id in ("robot-a", "robot-b"), "Unknown robot.")
        r = robot(self.world, report.robot_id)
        require(r["task"] and report.task_id == r["task"]["id"], "Arrival task does not match.")
        require(report.location == r["task"]["location"] == "homebase", "Wrong destination.")
        require(not r["physical"]["stopped"] and not r["physical"]["blocked"], "Robot is stopped or blocked.")
        if report.robot_id in self.objective["arrived"]:
            return  # Identical active task arrival is idempotent.
        require(r["task"]["status"] == "NAVIGATING", "Robot is not navigating.")
        p = report.sample
        require(p.session_id == report.session_id and p.robot_id == report.robot_id, "Pose identity does not match.")
        previous = datetime.fromisoformat(r["physical"]["pose_updated_at"])
        require(previous < p.timestamp <= self.now and self.now - p.timestamp <= timedelta(seconds=5), "Arrival pose is stale.")
        home = self.world["map"]["locations"]["homebase"]
        require(abs(p.pose.x - home["x"]) <= 1 and abs(p.pose.y - home["y"]) <= 1, "Robot has not reached Home.")
        r["physical"].update(pose=p.pose.model_dump(), pose_updated_at=p.timestamp.isoformat(), tracking="TRACKED")
        r["game"]["location"] = "homebase"
        r["task"]["status"] = "ACTIVE"
        self.sync_task(r["id"])
        self.positions.append(p)
        self.objective["arrived"].append(report.robot_id)
        self.emit("robot_arrived", f'{r["name"]} is Home with their contribution to the order. One step closer, together!', r["id"], location="homebase")
        self.objective["phase"] = "BOTH_ARRIVED" if len(self.objective["arrived"]) == 2 else "ONE_ARRIVED"

    def share_and_complete(self):
        require(self.world["game"]["status"] == "RUNNING", "Game is not running.")
        require(self.objective["phase"] == "BOTH_ARRIVED", "Handoff requires both confirmed arrivals.")
        require(set(self.objective["arrived"]) == {"robot-a", "robot-b"}, "Both arrivals are required.")
        a, b = robot(self.world, "robot-a"), robot(self.world, "robot-b")
        home = self.world["map"]["locations"]["homebase"]
        for r in (a, b):
            p = r["physical"]
            require(r["game"]["location"] == "homebase" and r["task"]["status"] == "ACTIVE"
                    and not p["stopped"] and not p["blocked"] and p["tracking"] == "TRACKED"
                    and p["pose"] is not None and abs(p["pose"]["x"] - home["x"]) <= 1
                    and abs(p["pose"]["y"] - home["y"]) <= 1, "Both robots must remain at Home.")
        ai, bi = a["game"]["inventory"], b["game"]["inventory"]
        require(ai.get("wheat", 0) >= 1 and bi.get("fish", 0) >= 1, "Order resources are missing.")
        bi["fish"] -= 1
        ai["fish"] = ai.get("fish", 0) + 1
        self.emit("resource_shared", "Milo hands Billy a fish at Home. With Billy's wheat, our order has everything it needs!",
                  "robot-b", from_robot_id="robot-b", to_robot_id="robot-a", item="fish", quantity=1,
                  giver_balance=bi["fish"], receiver_balance=ai["fish"])
        ai["fish"] -= 1
        ai["wheat"] -= 1
        for r in (a, b):
            r["task"].update(status="COMPLETED", progress=1)
            self.sync_task(r["id"])
            self.emit("task_completed", f'{r["name"]} completed their part of our order. Nice teamwork!', r["id"])
            r["task"] = None
        # A fixed shared-order reward, not proceeds from Milo's unexecuted sale.
        reward_split = {"robot-a": 5, "robot-b": 5}
        for r in (a, b):
            r["game"]["money"] += reward_split[r["id"]]
            self.emit("gold_updated", f'{r["name"]} receives 5 gold as their share of the order reward.',
                      r["id"], delta=5, balance=r["game"]["money"], source="shared_order_reward")
        self.world["game"]["goal"]["current"] = sum(r["game"]["money"] for r in self.world["robots"])
        self.objective["phase"] = "COMPLETED"
        self.emit("joint_task_completed", "Order complete! One wheat, one fish, and a little teamwork. Billy and Milo share 10 gold, 5 each!",
                  consumed={"wheat": 1, "fish": 1}, produced={}, reward_gold=10, reward_split=reward_split)
