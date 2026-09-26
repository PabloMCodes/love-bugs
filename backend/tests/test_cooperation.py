import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agents.protocol import AgentAction
from app.config import Settings
from app.game.cooperation import ArrivalReport, OrderRules, RuleViolation
from app.main import create_app
from app.persistence.store import Store
from app.schemas import Pose, PositionSample
from app.simulation.cooperation import CooperationDemo, SimulationCommand
from app.simulation.simulator import seed_session


class CooperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings(database_url=None, sqlite_path=str(Path(self.tmp.name) / "demo.sqlite3"))
        self.store = Store(self.settings)
        self.store.initialize()
        self.demo = CooperationDemo(self.store, seed_session(self.store))

    def step(self, operation="advance"):
        snapshot = self.demo.snapshot()
        return self.demo.execute(operation, SimulationCommand(
            session_id=snapshot["world"]["session_id"], expected_revision=snapshot["world"]["revision"]))

    def test_successful_sequence_and_opportunity_cost(self):
        state = self.step("start")
        original_money = [r["game"]["money"] for r in state["world"]["robots"]]
        world_keys = set(state["world"])
        phases = ["HELP_REQUESTED", "HELP_ACCEPTED", "TRAVELING_HOME", "ONE_ARRIVED", "BOTH_ARRIVED", "COMPLETED"]
        for phase in phases:
            state = self.step()
            self.assertEqual(state["objective"]["phase"], phase)
            self.assertEqual(set(state["world"]), world_keys)
            self.assertEqual(state["objective"], self.store.objective(self.demo.session_id))
            if phase != "COMPLETED":
                self.assertEqual(state["world"]["robots"][1]["game"]["inventory"]["fish"], 1)
                self.assertEqual([r["game"]["money"] for r in state["world"]["robots"]], original_money)
                self.assertEqual(state["world"]["game"]["goal"]["current"], 80)
        a, b = state["world"]["robots"]
        self.assertEqual(a["game"]["inventory"], {"wheat": 0, "fish": 0})
        self.assertEqual(b["game"]["inventory"]["fish"], 0)
        self.assertEqual([r["game"]["money"] for r in (a, b)], [m + 5 for m in original_money])
        self.assertEqual(state["world"]["game"]["goal"]["current"], 90)
        self.assertTrue(all(r["game"]["location"] == "homebase" and r["task"] is None for r in (a, b)))
        self.assertEqual(state["objective"]["forgone_sale_value"], 12)
        decisions = [e for e in state["world"]["events"] if e["type"] == "agent_decision"]
        self.assertIn("12 gold", decisions[0]["message"])
        self.assertEqual(decisions[0]["data"]["action"], "HELP_PARTNER")
        events = state["world"]["events"]
        self.assertEqual(state["objective"]["requirements"], {"wheat": 1, "fish": 1})
        self.assertEqual(state["objective"]["reward_split"], {"robot-a": 5, "robot-b": 5})
        self.assertEqual(state["objective"]["tasks"][0]["action"], "FULFILL_ORDER")
        self.assertFalse(any("meal" in r["game"]["inventory"] for r in (a, b)))
        self.assertFalse(any("meal" in e["message"].lower() for e in events))
        issued = next(e for e in events if e["type"] == "scenario_started")
        self.assertEqual(issued["data"]["issued_by"], "human")
        paid = [e for e in events if e["type"] == "gold_updated"]
        self.assertEqual([(e["robot_id"], e["data"]["delta"], e["data"]["balance"]) for e in paid],
                         [("robot-a", 5, 45), ("robot-b", 5, 45)])
        completed = next(e for e in events if e["type"] == "joint_task_completed")
        self.assertEqual(completed["data"]["consumed"], {"wheat": 1, "fish": 1})
        self.assertEqual(completed["data"]["produced"], {})
        self.assertEqual(completed["data"]["reward_gold"], 10)
        self.assertNotIn("owner_robot_id", completed["data"])
        ordered = [e["type"] for e in events if e["type"] in
                   {"help_requested", "help_accepted", "traveling_home", "resource_shared", "joint_task_completed"}]
        self.assertEqual(ordered, ["help_requested", "help_accepted", "traveling_home", "traveling_home",
                                   "resource_shared", "joint_task_completed"])
        self.assertTrue(all(e["data"].get("reason") for e in events if "objective_id" in e["data"]))
        self.assertEqual([m["sender_id"] for m in state["objective"]["messages"]], ["robot-a", "robot-b"])
        self.assertEqual(len(self.store.robot_history(self.demo.session_id, "robot-b")["position_samples"]), 4)
        with self.assertRaises(RuleViolation):
            self.step()  # Completion cannot pay the order reward twice.
        self.assertEqual(self.demo.snapshot(), state)

    def test_early_handoff_rejected_without_mutation(self):
        self.step("start")
        for _ in range(4):
            self.step()
        state = self.demo.snapshot()
        self.assertEqual(state["objective"]["arrived"], ["robot-a"])
        world, objective = deepcopy(state["world"]), deepcopy(state["objective"])
        rules = OrderRules(world, objective, datetime.now(timezone.utc))
        with self.assertRaisesRegex(RuleViolation, "both confirmed"):
            rules.share_and_complete()
        self.assertEqual(world, state["world"])
        self.assertEqual(objective, state["objective"])
        self.assertEqual(rules.events, [])
        self.assertEqual(self.demo.snapshot(), state)

    def test_arrival_validation_and_duplicate_report(self):
        self.step("start")
        for _ in range(3):
            self.step()
        state = self.demo.snapshot()
        now = datetime.now(timezone.utc) + timedelta(seconds=1)
        world, objective = state["world"], state["objective"]
        a = world["robots"][0]
        report = ArrivalReport(session_id=world["session_id"], robot_id=a["id"], task_id=a["task"]["id"],
                               location="homebase", sample=PositionSample(session_id=world["session_id"],
                               robot_id=a["id"], timestamp=now, source="simulation", pose=Pose(x=50, y=50, heading=0)))
        for bad in (report.model_copy(update={"session_id": "old"}),
                    report.model_copy(update={"task_id": "wrong"}),
                    report.model_copy(update={"sample": report.sample.model_copy(update={"pose": Pose(x=20, y=30, heading=0)})}),
                    report.model_copy(update={"sample": report.sample.model_copy(update={"timestamp": now - timedelta(seconds=10)})})):
            with self.assertRaises(RuleViolation):
                OrderRules(deepcopy(world), deepcopy(objective), now).arrive(bad)
        rules = OrderRules(world, objective, now)
        rules.arrive(report)
        rules.arrive(report)
        self.assertEqual(len(rules.events), 1)
        self.assertEqual(objective["arrived"], ["robot-a"])

    def test_unmatched_acceptance_and_missing_resources(self):
        self.step("start")
        state = self.step()
        rules = OrderRules(state["world"], state["objective"], datetime.now(timezone.utc))
        proposal = AgentAction(session_id=self.demo.session_id, objective_id=state["objective"]["id"],
                               robot_id="robot-b", action="HELP_PARTNER", request_id="not-a-request", reason="Help Billy")
        with self.assertRaisesRegex(RuleViolation, "matching help request"):
            rules.apply_action(proposal)
        for _ in range(4):
            state = self.step()
        state["world"]["robots"][1]["game"]["inventory"]["fish"] = 0
        with self.assertRaisesRegex(RuleViolation, "resources"):
            OrderRules(state["world"], state["objective"], datetime.now(timezone.utc)).share_and_complete()

    def test_transaction_failure_keeps_world_events_and_objective(self):
        self.step("start")
        for _ in range(5):
            self.step()
        before = self.demo.snapshot()
        original = self.store.execute
        def fail_objective(conn, sql, params=()):
            if "INSERT INTO cooperation_state" in sql:
                raise RuntimeError("Injected final-write failure")
            return original(conn, sql, params)
        with patch.object(self.store, "execute", side_effect=fail_objective):
            with self.assertRaises(RuntimeError):
                self.step()
        self.assertEqual(self.demo.snapshot(), before)

    def test_reset_after_reward_clears_order_and_balances(self):
        self.step("start")
        for _ in range(6):
            completed = self.step()
        old_session = self.demo.session_id
        reset = self.step("reset")
        self.assertIsNone(reset["objective"])
        self.assertEqual(reset["world"]["game"]["goal"]["current"], 80)
        self.assertEqual([r["game"]["money"] for r in reset["world"]["robots"]], [40, 40])
        self.assertTrue(all(r["game"]["inventory"] == {} for r in reset["world"]["robots"]))
        self.assertEqual(self.store.world(old_session), completed["world"])

    def test_api_reset_and_stale_requests(self):
        with TestClient(create_app(self.settings)) as client:
            def command(state):
                return {"session_id": state["world"]["session_id"], "expected_revision": state["world"]["revision"]}
            state = client.get("/simulation/cooperation").json()
            start = command(state)
            state = client.post("/simulation/cooperation/start", json=start).json()
            self.assertEqual(client.post("/simulation/cooperation/start", json=start).status_code, 409)
            old_session = state["world"]["session_id"]
            for _ in range(4):
                state = client.post("/simulation/cooperation/advance", json=command(state)).json()
            stale = command(state)
            reset = client.post("/simulation/cooperation/reset", json=stale).json()
            self.assertNotEqual(reset["world"]["session_id"], old_session)
            self.assertIsNone(reset["objective"])
            self.assertEqual(reset["world"]["game"]["status"], "READY")
            self.assertTrue(all(r["game"]["inventory"] == {} and r["task"] is None for r in reset["world"]["robots"]))
            self.assertEqual(client.get("/world").json(), reset["world"])
            self.assertEqual(client.post("/simulation/cooperation/advance", json=stale).status_code, 409)
            self.assertEqual(self.store.objective(old_session)["phase"], "ONE_ARRIVED")
            with client.websocket_connect("/events") as socket:
                first = socket.receive_json()["data"]
                reset2 = client.post("/simulation/cooperation/reset", json=command(reset)).json()
                second = socket.receive_json()["data"]
                self.assertEqual(first["revision"], second["revision"])
                self.assertEqual(second["session_id"], reset2["world"]["session_id"])
            restarted = client.post("/simulation/cooperation/start", json=command(reset2))
            self.assertEqual(restarted.status_code, 200)
