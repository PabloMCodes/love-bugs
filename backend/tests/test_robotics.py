from datetime import datetime, timedelta
import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.state import WorldStore


class PoseRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = WorldStore()
        self.client = TestClient(create_app(world_store=self.store))
        world = self.store.snapshot()
        self.timestamp = world.robots[0].physical.pose_updated_at + timedelta(seconds=1)
        self.report = {
            'session_id': world.session_id,
            'pose': {'x': 42.1, 'y': 63.5, 'heading': 91.2},
            'timestamp': self.timestamp.isoformat(),
        }

    def tearDown(self):
        self.client.close()

    def test_new_pose_updates_authoritative_world(self):
        previous_revision = self.store.snapshot().revision

        response = self.client.post('/robots/robot-a/pose', json=self.report)
        world = self.client.get('/world').json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'accepted': True})
        self.assertEqual(world['revision'], previous_revision + 1)
        self.assertEqual(
            world['robots'][0]['physical']['pose'],
            {'x': 42.1, 'y': 63.5, 'heading': 91.2},
        )
        self.assertEqual(world['robots'][0]['physical']['tracking'], 'TRACKED')
        self.assertEqual(
            datetime.fromisoformat(world['robots'][0]['physical']['pose_updated_at']),
            self.timestamp,
        )

    def test_older_or_equal_pose_is_ignored_without_revision_change(self):
        self.client.post('/robots/robot-a/pose', json=self.report)
        revision = self.store.snapshot().revision
        older = {
            **self.report,
            'pose': {'x': 1, 'y': 2, 'heading': 3},
            'timestamp': (self.timestamp - timedelta(seconds=1)).isoformat(),
        }

        equal_response = self.client.post('/robots/robot-a/pose', json=self.report)
        older_response = self.client.post('/robots/robot-a/pose', json=older)

        self.assertEqual(equal_response.json(), {'accepted': False})
        self.assertEqual(older_response.json(), {'accepted': False})
        self.assertEqual(self.store.snapshot().revision, revision)
        self.assertEqual(self.store.snapshot().robots[0].physical.pose.x, 42.1)

    def test_wrong_session_unknown_robot_and_out_of_bounds_are_rejected(self):
        wrong_session = self.client.post('/robots/robot-a/pose', json={
            **self.report,
            'session_id': 'old-session',
        })
        unknown_robot = self.client.post('/robots/unknown/pose', json=self.report)
        out_of_bounds = self.client.post('/robots/robot-a/pose', json={
            **self.report,
            'pose': {'x': 101, 'y': 50, 'heading': 0},
        })

        self.assertEqual(wrong_session.status_code, 409)
        self.assertEqual(wrong_session.json()['error']['code'], 'SESSION_MISMATCH')
        self.assertEqual(unknown_robot.status_code, 404)
        self.assertEqual(unknown_robot.json()['error']['code'], 'NOT_FOUND')
        self.assertEqual(out_of_bounds.status_code, 400)
        self.assertEqual(out_of_bounds.json()['error']['code'], 'INVALID_REQUEST')

    def test_timestamp_must_include_timezone(self):
        response = self.client.post('/robots/robot-a/pose', json={
            **self.report,
            'timestamp': datetime.now().isoformat(),
        })

        self.assertEqual(response.status_code, 422)


class HealthRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = WorldStore()
        self.client = TestClient(create_app(world_store=self.store))
        self.report = {
            'session_id': self.store.snapshot().session_id,
            'online': False,
            'battery': .35,
            'blocked': True,
        }

    def tearDown(self):
        self.client.close()

    def test_health_updates_authoritative_physical_state_and_events(self):
        previous_revision = self.store.snapshot().revision

        response = self.client.post('/robots/robot-a/health', json=self.report)
        world = self.store.snapshot()
        billy = world.robots[0]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'accepted': True})
        self.assertEqual(world.revision, previous_revision + 1)
        self.assertFalse(billy.physical.online)
        self.assertEqual(billy.physical.battery, .35)
        self.assertTrue(billy.physical.blocked)
        self.assertEqual(
            [event.type for event in world.events[-2:]],
            ['robot_offline', 'robot_blocked'],
        )

    def test_identical_health_heartbeat_does_not_publish_another_revision(self):
        self.client.post('/robots/robot-a/health', json=self.report)
        revision = self.store.snapshot().revision

        response = self.client.post('/robots/robot-a/health', json=self.report)

        self.assertEqual(response.json(), {'accepted': True})
        self.assertEqual(self.store.snapshot().revision, revision)

    def test_health_allows_unknown_battery(self):
        response = self.client.post('/robots/robot-a/health', json={
            **self.report,
            'battery': None,
        })

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.store.snapshot().robots[0].physical.battery)

    def test_invalid_health_reports_are_rejected(self):
        wrong_session = self.client.post('/robots/robot-a/health', json={
            **self.report,
            'session_id': 'old-session',
        })
        unknown_robot = self.client.post('/robots/unknown/health', json=self.report)
        invalid_battery = self.client.post('/robots/robot-a/health', json={
            **self.report,
            'battery': 1.1,
        })

        self.assertEqual(wrong_session.status_code, 409)
        self.assertEqual(wrong_session.json()['error']['code'], 'SESSION_MISMATCH')
        self.assertEqual(unknown_robot.status_code, 404)
        self.assertEqual(unknown_robot.json()['error']['code'], 'NOT_FOUND')
        self.assertEqual(invalid_battery.status_code, 422)


if __name__ == '__main__':
    unittest.main()
