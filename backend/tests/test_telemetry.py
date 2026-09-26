from datetime import datetime, timedelta, timezone
import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.state import WorldStore, default_world


class TelemetryFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.store = WorldStore(default_world('hardware'))
        self.client = TestClient(create_app(world_store=self.store))
        self.session_id = self.store.snapshot().session_id
        self.observed_at = datetime.now(timezone.utc)
        self.client.post('/robots/robot-a/health', json={
            'session_id': self.session_id,
            'online': True,
            'battery': .7,
            'blocked': False,
        }).raise_for_status()
        self.client.post('/robots/robot-a/pose', json={
            'session_id': self.session_id,
            'pose': {'x': 12, 'y': 30, 'heading': 0},
            'timestamp': self.observed_at.isoformat(),
        }).raise_for_status()

    def tearDown(self):
        self.client.close()

    def test_expiration_marks_offline_and_stale_without_dropping_task_or_pose(self):
        self.client.post('/game/start').raise_for_status()
        task = self.client.post('/tasks', json={
            'request_id': 'telemetry-task',
            'robot_id': 'robot-a',
            'action': 'MOVE_TO',
            'location': 'farm',
            'parameters': {},
        }).json()
        before = self.store.snapshot()

        expired = self.store.expire_stale_telemetry(
            datetime.now(timezone.utc) + timedelta(seconds=10),
            health_timeout_seconds=5,
            pose_timeout_seconds=2,
        )
        billy = expired.robots[0]

        self.assertFalse(billy.physical.online)
        self.assertEqual(billy.physical.tracking, 'STALE')
        self.assertEqual(billy.physical.pose, before.robots[0].physical.pose)
        self.assertEqual(billy.task.id, task['id'])
        self.assertEqual(
            [event.type for event in expired.events[-2:]],
            ['robot_offline', 'tracking_stale'],
        )
        self.assertEqual(expired.events[-2].data['reason'], 'health_timeout')
        self.assertEqual(expired.events[-1].data['reason'], 'pose_timeout')

        revision = expired.revision
        duplicate = self.store.expire_stale_telemetry(
            datetime.now(timezone.utc) + timedelta(seconds=20),
            health_timeout_seconds=5,
            pose_timeout_seconds=2,
        )
        self.assertEqual(duplicate.revision, revision)

    def test_fresh_reports_restore_availability(self):
        self.store.expire_stale_telemetry(
            datetime.now(timezone.utc) + timedelta(seconds=10),
            health_timeout_seconds=5,
            pose_timeout_seconds=2,
        )
        refreshed_at = self.observed_at + timedelta(seconds=20)

        health = self.client.post('/robots/robot-a/health', json={
            'session_id': self.session_id,
            'online': True,
            'battery': .65,
            'blocked': False,
        })
        pose = self.client.post('/robots/robot-a/pose', json={
            'session_id': self.session_id,
            'pose': {'x': 13, 'y': 31, 'heading': 5},
            'timestamp': refreshed_at.isoformat(),
        })
        billy = self.store.snapshot().robots[0]

        self.assertEqual(health.json(), {'accepted': True})
        self.assertEqual(pose.json(), {'accepted': True})
        self.assertTrue(billy.physical.online)
        self.assertEqual(billy.physical.tracking, 'TRACKED')
        self.assertEqual((billy.physical.pose.x, billy.physical.pose.y), (13, 31))

    def test_stale_tracking_pauses_active_work_until_pose_recovers(self):
        self.client.post('/game/start').raise_for_status()
        task = self.client.post('/tasks', json={
            'request_id': 'telemetry-fishing',
            'robot_id': 'robot-a',
            'action': 'FISH',
            'location': 'lake',
            'parameters': {},
        }).json()
        self.client.post('/robots/robot-a/arrived', json={
            'session_id': self.session_id,
            'task_id': task['id'],
            'location': 'lake',
        }).raise_for_status()
        self.store.expire_stale_telemetry(
            datetime.now(timezone.utc) + timedelta(seconds=10),
            health_timeout_seconds=100,
            pose_timeout_seconds=2,
        )

        self.store.advance_activities(1)
        paused = self.store.snapshot().robots[0]
        self.assertEqual(paused.physical.tracking, 'STALE')
        self.assertEqual(paused.task.progress, 0)

        self.client.post('/robots/robot-a/pose', json={
            'session_id': self.session_id,
            'pose': {'x': 12, 'y': 30, 'heading': 0},
            'timestamp': (self.observed_at + timedelta(seconds=20)).isoformat(),
        }).raise_for_status()
        self.store.advance_activities(1)
        recovered = self.store.snapshot().robots[0]
        self.assertEqual(recovered.physical.tracking, 'TRACKED')
        self.assertGreater(recovered.task.progress, 0)

    def test_simulation_mode_is_not_expired(self):
        store = WorldStore(default_world('simulation'))
        before = store.snapshot()

        after = store.expire_stale_telemetry(
            datetime.now(timezone.utc) + timedelta(days=1),
            health_timeout_seconds=1,
            pose_timeout_seconds=1,
        )

        self.assertEqual(after, before)

    def test_expiration_arguments_are_validated(self):
        with self.assertRaisesRegex(ValueError, 'timezone'):
            self.store.expire_stale_telemetry(
                datetime.now(),
                health_timeout_seconds=5,
                pose_timeout_seconds=2,
            )
        with self.assertRaisesRegex(ValueError, 'positive'):
            self.store.expire_stale_telemetry(
                datetime.now(timezone.utc),
                health_timeout_seconds=0,
                pose_timeout_seconds=2,
            )


if __name__ == '__main__':
    unittest.main()
