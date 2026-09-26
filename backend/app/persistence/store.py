"""Small transactional store using SQL common to SQLite and PostgreSQL."""
import json
import sqlite3
from datetime import timezone
from contextlib import contextmanager

from app.config import Settings
from app.schemas import Event, Pose, PositionSample


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.postgres = bool(settings.database_url)

    @contextmanager
    def connection(self):
        if self.postgres:
            import psycopg
            conn = psycopg.connect(self.settings.database_url, connect_timeout=10)
        else:
            conn = sqlite3.connect(self.settings.sqlite_path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def execute(self, conn, sql, params=()):
        return conn.execute(sql.replace("?", "%s") if self.postgres else sql, params)

    def initialize(self):
        with self.connection() as conn:
            if self.postgres:
                # Serialize schema migration across simultaneous server starts.
                conn.execute("SELECT pg_advisory_xact_lock(70624001)")
                if not conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'").fetchone():
                    raise RuntimeError("PostgreSQL requires the TimescaleDB extension (2.13+).")
            conn.execute("""CREATE TABLE IF NOT EXISTS world_state (
                session_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS cooperation_state (
                session_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS robot_events (
                session_id TEXT NOT NULL, id TEXT NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL, type TEXT NOT NULL,
                robot_id TEXT, task_id TEXT, message TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY (session_id, id, timestamp))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS robot_positions (
                session_id TEXT NOT NULL, robot_id TEXT NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL, source TEXT NOT NULL,
                x DOUBLE PRECISION NOT NULL, y DOUBLE PRECISION NOT NULL,
                heading DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (session_id, robot_id, timestamp))""")
            # A time-partitioned table cannot enforce event-ID uniqueness alone.
            # Preserve the public event identity contract in a small regular table.
            conn.execute("""CREATE TABLE IF NOT EXISTS event_ids (
                session_id TEXT NOT NULL, id TEXT NOT NULL,
                PRIMARY KEY (session_id, id))""")
            conn.execute("""INSERT INTO event_ids (session_id, id)
                SELECT DISTINCT session_id, id FROM robot_events WHERE true
                ON CONFLICT (session_id, id) DO NOTHING""")
            if self.postgres:
                key = conn.execute("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
                    WHERE conrelid = 'robot_events'::regclass AND contype = 'p'""").fetchone()
                if key and key[0] == "PRIMARY KEY (session_id, id)":
                    conn.execute("ALTER TABLE robot_events DROP CONSTRAINT robot_events_pkey")
                    conn.execute("""ALTER TABLE robot_events ADD PRIMARY KEY
                        (session_id, id, timestamp)""")
                for table in ("robot_positions", "robot_events"):
                    conn.execute("""SELECT create_hypertable(%s::regclass, by_range('timestamp'),
                        if_not_exists => TRUE, migrate_data => TRUE)""", (table,))
            conn.execute("""CREATE INDEX IF NOT EXISTS events_robot_recent
                ON robot_events (session_id, robot_id, timestamp DESC, id DESC)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS events_recent
                ON robot_events (session_id, timestamp DESC, id DESC)""")

    def commit(self, world: dict, events: list[Event], positions: list[PositionSample], objective=None):
        """Atomically publish validated state and its history; errors roll back all writes.

        Callers own game validation and serialize state mutations. Duplicate IDs fail
        rather than applying a partially duplicated batch. No public raw-event writer.
        """
        session_id = world["session_id"]
        if any(p.session_id != session_id for p in positions):
            raise ValueError("Position session does not match world")
        snapshot = {**world, "events": []}  # Feed is always read from history.
        with self.connection() as conn:
            for event in events:
                self.execute(conn, "INSERT INTO event_ids VALUES (?, ?)", (session_id, event.id))
                self.execute(conn, "INSERT INTO robot_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (session_id, event.id, event.timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds"), event.type,
                              event.robot_id, event.task_id, event.message, json.dumps(event.data)))
            for p in positions:
                self.execute(conn, "INSERT INTO robot_positions VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (p.session_id, p.robot_id, p.timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds"), p.source,
                              p.pose.x, p.pose.y, p.pose.heading))
            self.execute(conn, """INSERT INTO world_state VALUES (?, ?)
                ON CONFLICT (session_id) DO UPDATE SET snapshot = excluded.snapshot""",
                         (session_id, json.dumps(snapshot)))
            if objective is not None:
                self.execute(conn, """INSERT INTO cooperation_state VALUES (?, ?)
                    ON CONFLICT (session_id) DO UPDATE SET snapshot = excluded.snapshot""",
                             (session_id, json.dumps(objective)))

    def objective(self, session_id):
        with self.connection() as conn:
            row = self.execute(conn, "SELECT snapshot FROM cooperation_state WHERE session_id = ?",
                               (session_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def recent_events(self, session_id: str, limit: int = 100, conn=None, robot_id=None):
        if conn is None:
            with self.connection() as connection:
                return self.recent_events(session_id, limit, connection, robot_id)
        robot_filter = " AND robot_id = ?" if robot_id is not None else ""
        params = (session_id, robot_id, limit) if robot_id is not None else (session_id, limit)
        rows = self.execute(conn, """SELECT id, timestamp, type, robot_id, task_id, message, data
            FROM robot_events WHERE session_id = ?""" + robot_filter +
            " ORDER BY timestamp DESC, id DESC LIMIT ?", params).fetchall()
        return [Event(id=r[0], timestamp=r[1], type=r[2], robot_id=r[3], task_id=r[4],
                      message=r[5], data=json.loads(r[6])).model_dump(mode="json")
                for r in reversed(rows)]

    def world(self, session_id: str):
        with self.connection() as conn:
            # One consistent view when future game mutations run concurrently.
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                         if self.postgres else "BEGIN")
            row = self.execute(conn, "SELECT snapshot FROM world_state WHERE session_id = ?",
                               (session_id,)).fetchone()
            world = json.loads(row[0])
            world["events"] = self.recent_events(session_id, conn=conn)
            return world

    def robot_history(self, session_id: str, robot_id: str, limit: int = 100):
        """Latest bounded samples and robot-specific events, each oldest first."""
        with self.connection() as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                         if self.postgres else "BEGIN")
            row = self.execute(conn, "SELECT snapshot FROM world_state WHERE session_id = ?",
                               (session_id,)).fetchone()
            world = json.loads(row[0])
            if robot_id not in {robot["id"] for robot in world["robots"]}:
                raise KeyError(robot_id)
            rows = self.execute(conn, """SELECT timestamp, source, x, y, heading
                FROM robot_positions WHERE session_id = ? AND robot_id = ?
                ORDER BY timestamp DESC LIMIT ?""", (session_id, robot_id, limit)).fetchall()
            samples = [PositionSample(session_id=session_id, robot_id=robot_id,
                       timestamp=r[0], source=r[1], pose=Pose(x=r[2], y=r[3], heading=r[4]))
                       .model_dump(mode="json") for r in reversed(rows)]
            return {"session_id": session_id, "robot_id": robot_id, "mode": world["mode"],
                    "position_samples": samples,
                    "events": self.recent_events(session_id, limit, conn, robot_id)}
