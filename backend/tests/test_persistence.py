import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.persistence.store import Store


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings(database_url=None, sqlite_path=str(Path(self.tmp.name) / 'test.sqlite3'))

    def test_live_flow_and_restart_history(self):
        app = create_app(settings=self.settings, run_simulator=False)
        with TestClient(app) as client:
            first = client.get('/world').json()
            sid = first['session_id']
            self.assertEqual(first['map']['locations']['homebase'], {'x': 50.0, 'y': 30.0})
            client.post('/game/start').raise_for_status()
            request = {'request_id': 'fish', 'robot_id': 'robot-a', 'action': 'FISH',
                       'location': 'lake', 'reason': 'Collect fish together.'}
            task = client.post('/tasks', json=request)
            self.assertEqual(task.status_code, 202)
            revision = client.get('/world').json()['revision']
            self.assertEqual(client.post('/tasks', json=request).json(), task.json())
            self.assertEqual(client.get('/world').json()['revision'], revision)
            for _ in range(40):
                app.state.simulator.tick()
            final = client.get('/world').json()
            self.assertIsNone(final['robots'][0]['task'])
            self.assertEqual(final['robots'][0]['game']['inventory']['fish']['quantity'], 1)
            self.assertEqual(Store(self.settings).world(sid), final)
            events = client.get('/events').json()['events']
            self.assertEqual(events, final['events'])
            self.assertEqual(sum(e['type'] == 'task_completed' for e in events), 1)
            history = client.get('/robots/robot-a/history').json()
            self.assertGreater(len(history['position_samples']), 2)
            self.assertTrue(all(p['source'] == 'simulation' for p in history['position_samples']))
            self.assertEqual(client.get('/robots/missing/history').status_code, 404)
            self.assertEqual(client.get('/robots/robot-a/history?session_id=missing').status_code, 404)
            app.state.history.initialize()
            self.assertEqual(client.get('/events').json()['events'], events)
        with TestClient(create_app(settings=self.settings, run_simulator=False)) as client:
            self.assertNotEqual(client.get('/world').json()['session_id'], sid)
            self.assertEqual(client.get('/events', params={'session_id': sid}).json()['events'], events)

    def test_failed_write_rolls_back_world_events_and_retry_key(self):
        app = create_app(settings=self.settings, run_simulator=False)
        with TestClient(app) as client:
            client.post('/game/start').raise_for_status()
            before = client.get('/world').json()
            request = {'request_id': 'retry', 'robot_id': 'robot-a', 'action': 'MOVE_TO', 'location': 'farm'}
            real_execute = app.state.history.execute
            def fail_snapshot(conn, sql, params=()):
                if 'INSERT INTO world_state' in sql:
                    raise RuntimeError('private database details')
                return real_execute(conn, sql, params)
            with patch.object(app.state.history, 'execute', side_effect=fail_snapshot):
                response = client.post('/tasks', json=request)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('private', response.text)
            self.assertEqual(client.get('/world').json(), before)
            self.assertEqual(Store(self.settings).world(before['session_id']), before)
            self.assertEqual(client.post('/tasks', json=request).status_code, 202)

    def test_pose_deduplication_and_source(self):
        from datetime import datetime, timedelta, timezone
        app = create_app(settings=self.settings, run_simulator=False)
        with TestClient(app) as client:
            sid = client.get('/world').json()['session_id']
            payload = {'session_id': sid, 'pose': {'x': 42, 'y': 60, 'heading': 90},
                       'timestamp': (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()}
            self.assertTrue(client.post('/robots/robot-a/pose', json=payload).json()['accepted'])
            self.assertFalse(client.post('/robots/robot-a/pose', json=payload).json()['accepted'])
            samples = client.get('/robots/robot-a/history').json()['position_samples']
            self.assertEqual(len(samples), 2)
            self.assertEqual(samples[-1]['source'], 'pose_report')

    def test_failed_arrival_write_can_be_retried_without_false_idempotency(self):
        app = create_app(settings=self.settings, run_simulator=False)
        with TestClient(app) as client:
            client.post('/game/start').raise_for_status()
            task = client.post('/tasks', json={
                'request_id': 'arrival-retry',
                'robot_id': 'robot-a',
                'action': 'MOVE_TO',
                'location': 'farm',
            }).json()
            report = {
                'session_id': client.get('/world').json()['session_id'],
                'task_id': task['id'],
                'location': 'farm',
            }
            before = client.get('/world').json()
            real_execute = app.state.history.execute

            def fail_snapshot(conn, sql, params=()):
                if 'INSERT INTO world_state' in sql:
                    raise RuntimeError('private database details')
                return real_execute(conn, sql, params)

            with patch.object(app.state.history, 'execute', side_effect=fail_snapshot):
                failed = client.post('/robots/robot-a/arrived', json=report)

            self.assertEqual(failed.status_code, 503)
            self.assertEqual(client.get('/world').json(), before)

            retry = client.post('/robots/robot-a/arrived', json=report)
            final = client.get('/world').json()
            self.assertEqual(retry.json(), {'accepted': True})
            self.assertIsNone(final['robots'][0]['task'])
            self.assertEqual(final['robots'][0]['game']['location'], 'farm')
            self.assertEqual(Store(self.settings).world(report['session_id']), final)

    def test_reset_starts_new_persisted_session_and_keeps_old_history(self):
        app = create_app(settings=self.settings, run_simulator=False)
        with TestClient(app) as client:
            started = client.post('/game/start').json()
            old_session = started['session_id']
            old_events = client.get('/events').json()['events']

            reset = client.post('/game/reset')
            fresh = reset.json()

            self.assertEqual(reset.status_code, 200)
            self.assertNotEqual(fresh['session_id'], old_session)
            self.assertEqual(fresh['revision'], 1)
            self.assertEqual(fresh['events'][0]['type'], 'game_ready')
            archived_events = client.get(
                '/events',
                params={'session_id': old_session},
            ).json()['events']
            self.assertEqual(archived_events[:len(old_events)], old_events)
            self.assertEqual(archived_events[-1]['type'], 'game_stopped')
            self.assertEqual(Store(self.settings).world(fresh['session_id']), fresh)
            for robot_id in ('robot-a', 'robot-b'):
                history = client.get(f'/robots/{robot_id}/history').json()
                self.assertEqual(len(history['position_samples']), 1)
                self.assertEqual(history['position_samples'][0]['source'], 'reset')

    @unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'Live Tiger Data credentials not configured')
    def test_tiger_insert_read(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from uuid import uuid4
        schema = 'smoke_' + uuid4().hex
        url = os.environ['TEST_DATABASE_URL']
        with psycopg.connect(url) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            settings = Settings(database_url=make_conninfo(url, options=f'-c search_path={schema},public'))
            app = create_app(settings=settings, run_simulator=False)
            with TestClient(app) as client:
                client.post('/game/start').raise_for_status()
                self.assertTrue(any(e['type'] == 'game_started' for e in client.get('/events').json()['events']))
                self.assertEqual(len(client.get('/robots/robot-a/history').json()['position_samples']), 1)
                app.state.history.initialize()
                with app.state.history.connection() as conn:
                    tables = conn.execute('SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_schema = %s', (schema,)).fetchall()
                    self.assertEqual({r[0] for r in tables}, {'robot_events', 'robot_positions'})
        finally:
            with psycopg.connect(url) as conn:
                conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
