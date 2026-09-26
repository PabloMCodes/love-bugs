import os
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.persistence.store import Store
from app.schemas import Event, Pose, PositionSample
from app.simulation.simulator import seed_session


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(database_url=None, sqlite_path=str(Path(self.tmp.name) / "test.sqlite3"))
        self.addCleanup(self.tmp.cleanup)

    def test_api_contract_and_restart(self):
        with TestClient(create_app(self.settings)) as client:
            world = client.get("/world").json()
            self.assertEqual(world["schema_version"], 1)
            self.assertEqual(world["mode"], "simulation")
            self.assertTrue(all(not r["physical"]["online"] for r in world["robots"]))
            self.assertTrue(all("Simulated" in e["message"] for e in world["events"]))
            history = client.get("/robots/robot-a/history").json()
            self.assertEqual(history["session_id"], world["session_id"])
            self.assertEqual(history["position_samples"][0]["source"], "simulation")
            self.assertEqual(len(history["events"]), 1)
            self.assertEqual(client.get("/robots/missing/history").status_code, 404)
            self.assertEqual(client.get("/robots/robot-a/history?limit=0").status_code, 400)
            self.assertEqual(client.get("/robots/robot-a/history?limit=1001").status_code, 400)
            self.assertEqual(world["game"]["status"], "READY")
            self.assertEqual(len(world["robots"]), 2)
            self.assertTrue(all(r["game"]["location"] == "homebase" for r in world["robots"]))
            self.assertEqual(world["events"], client.get("/events").json()["events"])
            self.assertEqual(len(client.get("/events?limit=1").json()["events"]), 1)
            self.assertEqual(client.get("/events?limit=101").status_code, 400)
            self.assertEqual(client.get("/missing").json()["error"]["code"], "NOT_FOUND")
            with client.websocket_connect("/events") as ws:
                self.assertEqual(ws.receive_json(), {"type": "world_snapshot", "data": world})
            response = client.get("/world", headers={"Origin": "http://localhost:5173"})
            self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")
        with TestClient(create_app(self.settings)) as client:
            self.assertNotEqual(client.get("/world").json()["session_id"], world["session_id"])
        self.assertEqual(Store(self.settings).world(world["session_id"]), world)

    def test_atomic_history_and_telemetry(self):
        store = Store(self.settings)
        store.initialize()
        session = seed_session(store)
        before = store.world(session)
        with store.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM robot_positions").fetchone()[0], 2)
        changed = deepcopy(before)
        changed["revision"] += 1
        event = Event(timestamp=datetime.now(timezone.utc), type="agent_decision", message="Return Home")
        with self.assertRaises(Exception):
            store.commit(changed, [event, event], [])
        self.assertEqual(store.world(session), before)
        store.commit(changed, [event], [])
        self.assertEqual(store.world(session)["revision"], 2)
        self.assertEqual(len(store.recent_events(session)), 3)

    def test_schema_reinitialization_preserves_history(self):
        store = Store(self.settings)
        store.initialize()
        session = seed_session(store)
        before = store.world(session)
        # Prior SQLite databases have history but no event identity registry.
        with store.connection() as conn:
            conn.execute("DROP TABLE event_ids")
        store.initialize()
        self.assertEqual(store.world(session), before)
        with store.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM event_ids").fetchone()[0], 2)

    def test_history_order_limits_and_isolation(self):
        store = Store(self.settings)
        store.initialize()
        session = seed_session(store)
        world = store.world(session)
        start = datetime.now(timezone.utc) + timedelta(seconds=1)
        samples = [PositionSample(session_id=session, robot_id="robot-a", source="simulation",
                   timestamp=start + timedelta(seconds=i), pose=Pose(x=i, y=50, heading=0))
                   for i in range(3)]
        events = [Event(timestamp=p.timestamp, type="agent_decision", robot_id="robot-a",
                        message=f"Decision {i}") for i, p in enumerate(samples)]
        # Insertion order differs from observation time.
        store.commit(world, list(reversed(events)), list(reversed(samples)))
        other_session = seed_session(store)
        history = store.robot_history(session, "robot-a", limit=2)
        self.assertEqual([p["pose"]["x"] for p in history["position_samples"]], [1, 2])
        self.assertEqual([e["id"] for e in history["events"]], [e.id for e in events[1:]])
        self.assertEqual(len(store.robot_history(session, "robot-b")["events"]), 1)
        self.assertEqual(len(store.robot_history(other_session, "robot-a")["position_samples"]), 1)
        # Same event ID at a different time must still be rejected.
        replay = events[0].model_copy(update={"timestamp": start + timedelta(days=1)})
        with self.assertRaises(Exception):
            store.commit(world, [replay], [])
        self.assertEqual(len(store.robot_history(session, "robot-a")["events"]), 4)

    def test_invalid_telemetry(self):
        for values in ({"x": -1, "y": 50, "heading": 0}, {"x": 50, "y": 50, "heading": 360}):
            with self.assertRaises(ValidationError):
                Pose(**values)
        with self.assertRaises(ValidationError):
            PositionSample(session_id="s", robot_id="r", source="simulation",
                           timestamp="2026-09-26T12:00:00", pose=Pose(x=50, y=50, heading=0))

    def test_database_failure_is_sanitized(self):
        with TestClient(create_app(self.settings)) as client:
            with Store(self.settings).connection() as conn:
                conn.execute("DROP TABLE robot_events")
            response = client.get("/world")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "SUBSYSTEM_UNAVAILABLE")

    @unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL to a test PostgreSQL/Tiger database")
    def test_postgres(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from uuid import uuid4

        # Isolate the migration test from all application data.
        schema = "smoke_" + uuid4().hex
        url = os.environ["TEST_DATABASE_URL"]
        with psycopg.connect(url) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            settings = Settings(database_url=make_conninfo(url, options=f"-c search_path={schema},public"))
            store = Store(settings)
            # Simulate the first slice's populated, ordinary event table.
            with store.connection() as conn:
                conn.execute("""CREATE TABLE robot_events (
                    session_id TEXT NOT NULL, id TEXT NOT NULL, timestamp TIMESTAMPTZ NOT NULL,
                    type TEXT NOT NULL, robot_id TEXT, task_id TEXT, message TEXT NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY (session_id, id))""")
                conn.execute("""INSERT INTO robot_events VALUES
                    ('legacy', 'old-event', now(), 'robot_arrived', 'robot-a', NULL, 'Preserve me', '{}')""")
                conn.execute("""CREATE TABLE robot_positions (
                    session_id TEXT NOT NULL, robot_id TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL, source TEXT NOT NULL,
                    x DOUBLE PRECISION NOT NULL, y DOUBLE PRECISION NOT NULL,
                    heading DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (session_id, robot_id, timestamp))""")
                conn.execute("""INSERT INTO robot_positions VALUES
                    ('legacy', 'robot-a', now(), 'simulation', 50, 50, 0)""")
            store.initialize()
            session = seed_session(store)
            store.initialize()  # Initialization must also work on populated hypertables.
            self.assertEqual(store.recent_events("legacy")[0]["message"], "Preserve me")
            self.assertEqual(len(store.world(session)["events"]), 2)
            history = store.robot_history(session, "robot-a")
            self.assertEqual(len(history["position_samples"]), 1)
            self.assertEqual(history["position_samples"][0]["pose"]["x"], 50)
            self.assertEqual(len(history["events"]), 1)
            with store.connection() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM robot_positions WHERE session_id = 'legacy'").fetchone()[0], 1)
                tables = conn.execute("""SELECT hypertable_name FROM timescaledb_information.hypertables
                    WHERE hypertable_schema = %s""", (schema,)).fetchall()
                self.assertEqual({r[0] for r in tables}, {"robot_positions", "robot_events"})
            replay = Event.model_validate(history["events"][0])
            replay.timestamp += timedelta(seconds=1)
            with self.assertRaises(psycopg.IntegrityError):
                store.commit(store.world(session), [replay], [])
        finally:
            with psycopg.connect(url) as conn:
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))



if __name__ == "__main__":
    unittest.main()
