from datetime import datetime, timezone
import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.state import WorldStore, default_world


class LifecycleRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = WorldStore()
        self.client = TestClient(create_app(world_store=self.store))
        self.client.post('/game/start')

    def tearDown(self):
        self.client.close()

    def assign_move(self, robot_id='robot-a', request_id='lifecycle-move'):
        response = self.client.post('/tasks', json={
            'request_id': request_id,
            'robot_id': robot_id,
            'action': 'MOVE_TO',
            'location': 'farm',
            'parameters': {},
        })
        self.assertEqual(response.status_code, 202)
        return response.json()

    def test_game_stop_cancels_tasks_stops_fleet_and_resumes_safely(self):
        first_task = self.assign_move()
        second_task = self.assign_move('robot-b', 'lifecycle-move-b')

        response = self.client.post('/game/stop')
        stopped = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(stopped['game']['status'], 'STOPPED')
        self.assertTrue(all(robot['physical']['stopped'] for robot in stopped['robots']))
        self.assertTrue(all(robot['task'] is None for robot in stopped['robots']))
        cancelled_ids = {
            event['task_id']
            for event in stopped['events']
            if event['type'] == 'task_cancelled'
        }
        self.assertEqual(cancelled_ids, {first_task['id'], second_task['id']})
        self.assertEqual(stopped['events'][-1]['type'], 'game_stopped')

        revision = stopped['revision']
        duplicate = self.client.post('/game/stop').json()
        self.assertEqual(duplicate['revision'], revision)

        resumed = self.client.post('/game/start').json()
        self.assertEqual(resumed['game']['status'], 'RUNNING')
        self.assertTrue(all(not robot['physical']['stopped'] for robot in resumed['robots']))
        self.assertTrue(all(robot['task'] is None for robot in resumed['robots']))

        cancelled_retry = self.client.post('/tasks', json={
            'request_id': 'lifecycle-move',
            'robot_id': 'robot-a',
            'action': 'MOVE_TO',
            'location': 'farm',
            'parameters': {},
        })
        self.assertEqual(cancelled_retry.json()['status'], 'CANCELLED')

    def test_robot_stop_survives_game_restart_until_explicit_resume(self):
        task = self.assign_move()

        stopped_robot = self.client.post('/robots/robot-a/stop')
        stopped_world = self.store.snapshot()

        self.assertEqual(stopped_robot.status_code, 200)
        self.assertTrue(stopped_robot.json()['physical']['stopped'])
        self.assertIsNone(stopped_robot.json()['task'])
        self.assertFalse(stopped_world.robots[1].physical.stopped)
        self.assertIn(
            task['id'],
            [event.task_id for event in stopped_world.events if event.type == 'task_cancelled'],
        )

        revision = stopped_world.revision
        duplicate = self.client.post('/robots/robot-a/stop').json()
        self.assertEqual(self.store.snapshot().revision, revision)
        self.assertEqual(duplicate, stopped_robot.json())

        self.client.post('/game/stop')
        restarted = self.client.post('/game/start').json()
        billy, milo = restarted['robots']
        self.assertTrue(billy['physical']['stopped'])
        self.assertFalse(milo['physical']['stopped'])

        resumed = self.client.post('/robots/robot-a/resume')
        self.assertEqual(resumed.status_code, 200)
        self.assertFalse(resumed.json()['physical']['stopped'])
        self.assertEqual(self.store.snapshot().events[-1].type, 'robot_resumed')

    def test_resume_requires_running_game_and_healthy_robot(self):
        self.client.post('/robots/robot-a/stop')
        self.client.post('/game/stop')

        stopped_game = self.client.post('/robots/robot-a/resume')
        unknown = self.client.post('/robots/unknown/resume')

        self.assertEqual(stopped_game.status_code, 409)
        self.assertEqual(stopped_game.json()['error']['code'], 'GAME_NOT_RUNNING')
        self.assertEqual(unknown.status_code, 404)

        self.client.post('/game/start')
        self.client.post('/robots/robot-a/health', json={
            'session_id': self.store.snapshot().session_id,
            'online': False,
            'battery': .5,
            'blocked': False,
        })
        unavailable = self.client.post('/robots/robot-a/resume')
        self.assertEqual(unavailable.status_code, 409)
        self.assertEqual(unavailable.json()['error']['code'], 'ROBOT_UNAVAILABLE')

    def test_simulation_reset_creates_fresh_stopped_session_at_home(self):
        self.assign_move()
        previous_session = self.store.snapshot().session_id

        reset = self.client.post('/game/reset')
        world = reset.json()

        self.assertEqual(reset.status_code, 200)
        self.assertNotEqual(world['session_id'], previous_session)
        self.assertEqual(world['revision'], 1)
        self.assertEqual(world['game']['status'], 'READY')
        self.assertEqual(len(world['events']), 1)
        self.assertEqual(world['events'][0]['type'], 'game_ready')
        for robot in world['robots']:
            self.assertTrue(robot['physical']['stopped'])
            self.assertIsNone(robot['task'])
            self.assertEqual(robot['game']['location'], 'homebase')
            self.assertEqual(
                (robot['physical']['pose']['x'], robot['physical']['pose']['y']),
                (50, 30),
            )

        started = self.client.post('/game/start').json()
        self.assertTrue(all(not robot['physical']['stopped'] for robot in started['robots']))
        reused_request = self.client.post('/tasks', json={
            'request_id': 'lifecycle-move',
            'robot_id': 'robot-a',
            'action': 'MOVE_TO',
            'location': 'farm',
            'parameters': {},
        })
        self.assertEqual(reused_request.status_code, 202)
        self.assertEqual(reused_request.json()['status'], 'ASSIGNED')

    def test_hardware_reset_preserves_pose_but_requires_fresh_tracking(self):
        world = default_world()
        world['mode'] = 'hardware'
        timestamp = datetime.now(timezone.utc)
        world['robots'][0]['physical']['pose'] = {
            'x': 33,
            'y': 44,
            'heading': 120,
        }
        world['robots'][0]['physical']['pose_updated_at'] = timestamp
        store = WorldStore(world)
        with TestClient(create_app(world_store=store)) as client:
            reset = client.post('/game/reset').json()

        billy = reset['robots'][0]
        self.assertEqual(billy['physical']['pose'], {'x': 33, 'y': 44, 'heading': 120})
        self.assertEqual(
            datetime.fromisoformat(billy['physical']['pose_updated_at']),
            timestamp,
        )
        self.assertEqual(billy['physical']['tracking'], 'STALE')
        self.assertTrue(billy['physical']['stopped'])
        self.assertIsNone(billy['game']['location'])


if __name__ == '__main__':
    unittest.main()
