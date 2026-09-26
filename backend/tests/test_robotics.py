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


if __name__ == '__main__':
    unittest.main()
