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


class ArrivalRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = WorldStore()
        self.client = TestClient(create_app(world_store=self.store))
        self.client.post('/game/start')

    def tearDown(self):
        self.client.close()

    def assign_task(self, **overrides):
        request = {
            'request_id': 'arrival-request-001',
            'robot_id': 'robot-a',
            'action': 'MOVE_TO',
            'location': 'farm',
            'parameters': {},
        }
        request.update(overrides)
        response = self.client.post('/tasks', json=request)
        self.assertEqual(response.status_code, 202)
        return response.json()

    def test_arrival_completes_move_task_and_is_idempotent(self):
        task = self.assign_task()
        report = {
            'session_id': self.store.snapshot().session_id,
            'task_id': task['id'],
            'location': 'farm',
        }

        response = self.client.post('/robots/robot-a/arrived', json=report)
        arrived = self.store.snapshot()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'accepted': True})
        self.assertEqual(arrived.robots[0].game.location, 'farm')
        self.assertIsNone(arrived.robots[0].task)
        self.assertEqual(arrived.events[-2].type, 'robot_arrived')
        self.assertEqual(arrived.events[-1].type, 'task_completed')

        revision = arrived.revision
        duplicate = self.client.post('/robots/robot-a/arrived', json=report)
        self.assertEqual(duplicate.json(), {'accepted': True})
        self.assertEqual(self.store.snapshot().revision, revision)

    def test_arrival_starts_activity_without_granting_reward(self):
        task = self.assign_task(
            request_id='arrival-fish-001',
            action='FISH',
            location='lake',
        )
        before_quantity = self.store.snapshot().robots[0].game.inventory.get('fish')
        report = {
            'session_id': self.store.snapshot().session_id,
            'task_id': task['id'],
            'location': 'lake',
        }

        response = self.client.post('/robots/robot-a/arrived', json=report)
        arrived = self.store.snapshot()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(arrived.robots[0].task.status, 'ACTIVE')
        self.assertEqual(arrived.robots[0].task.progress, 0)
        self.assertEqual(arrived.robots[0].game.inventory.get('fish'), before_quantity)
        self.assertEqual(arrived.events[-2].type, 'robot_arrived')
        self.assertEqual(arrived.events[-1].type, 'task_started')

        revision = arrived.revision
        duplicate = self.client.post('/robots/robot-a/arrived', json=report)
        self.assertEqual(duplicate.json(), {'accepted': True})
        self.assertEqual(self.store.snapshot().revision, revision)

    def test_arrival_executes_purchase_only_once(self):
        task = self.assign_task(
            request_id='arrival-buy-001',
            robot_id='robot-b',
            action='BUY',
            location='market',
            parameters={'item': 'seeds', 'quantity': 2},
        )
        report = {
            'session_id': self.store.snapshot().session_id,
            'task_id': task['id'],
            'location': 'market',
        }

        first = self.client.post('/robots/robot-b/arrived', json=report)
        purchased = self.store.snapshot()
        quantity = purchased.robots[1].game.inventory['seeds'].quantity
        balance = purchased.robots[1].game.money
        revision = purchased.revision
        duplicate = self.client.post('/robots/robot-b/arrived', json=report)

        self.assertEqual(first.json(), {'accepted': True})
        self.assertEqual(duplicate.json(), {'accepted': True})
        self.assertEqual(quantity, 2)
        self.assertEqual(balance, 30)
        self.assertEqual(self.store.snapshot().robots[1].game.inventory['seeds'].quantity, 2)
        self.assertEqual(self.store.snapshot().robots[1].game.money, 30)
        self.assertEqual(self.store.snapshot().revision, revision)

    def test_mismatched_arrivals_are_rejected(self):
        task = self.assign_task()
        report = {
            'session_id': self.store.snapshot().session_id,
            'task_id': task['id'],
            'location': 'farm',
        }

        wrong_session = self.client.post('/robots/robot-a/arrived', json={
            **report,
            'session_id': 'old-session',
        })
        unknown_robot = self.client.post('/robots/unknown/arrived', json=report)
        wrong_task = self.client.post('/robots/robot-a/arrived', json={
            **report,
            'task_id': 'task-other',
        })
        wrong_location = self.client.post('/robots/robot-a/arrived', json={
            **report,
            'location': 'market',
        })

        self.assertEqual(wrong_session.status_code, 409)
        self.assertEqual(wrong_session.json()['error']['code'], 'SESSION_MISMATCH')
        self.assertEqual(unknown_robot.status_code, 404)
        self.assertEqual(unknown_robot.json()['error']['code'], 'NOT_FOUND')
        self.assertEqual(wrong_task.status_code, 409)
        self.assertEqual(wrong_task.json()['error']['code'], 'TASK_MISMATCH')
        self.assertEqual(wrong_location.status_code, 409)
        self.assertEqual(wrong_location.json()['error']['code'], 'TASK_MISMATCH')


class BlockedRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = WorldStore()
        self.client = TestClient(create_app(world_store=self.store))
        self.client.post('/game/start')
        task_response = self.client.post('/tasks', json={
            'request_id': 'blocked-request-001',
            'robot_id': 'robot-a',
            'action': 'MOVE_TO',
            'location': 'farm',
            'parameters': {},
        })
        self.assertEqual(task_response.status_code, 202)
        self.task = task_response.json()
        self.report = {
            'session_id': self.store.snapshot().session_id,
            'task_id': self.task['id'],
            'reason': 'obstacle',
            'duration_ms': 4000,
        }

    def tearDown(self):
        self.client.close()

    def test_blocked_report_pauses_navigation_and_emits_event(self):
        previous_revision = self.store.snapshot().revision

        response = self.client.post('/robots/robot-a/blocked', json=self.report)
        world = self.store.snapshot()
        billy = world.robots[0]
        event = world.events[-1]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'accepted': True})
        self.assertEqual(world.revision, previous_revision + 1)
        self.assertTrue(billy.physical.blocked)
        self.assertEqual(billy.task.id, self.task['id'])
        self.assertEqual(event.type, 'robot_blocked')
        self.assertEqual(event.task_id, self.task['id'])
        self.assertEqual(event.data, {'reason': 'obstacle', 'duration_ms': 4000})

        blocked_pose = billy.physical.pose.model_copy(deep=True)
        self.client.app.state.simulator.tick()
        after_tick = self.store.snapshot()
        self.assertEqual(after_tick.revision, world.revision)
        self.assertEqual(after_tick.robots[0].physical.pose, blocked_pose)

        recovery = self.client.post('/robots/robot-a/health', json={
            'session_id': self.store.snapshot().session_id,
            'online': True,
            'battery': .82,
            'blocked': False,
        })
        self.assertEqual(recovery.json(), {'accepted': True})
        recovered_revision = self.store.snapshot().revision
        self.client.app.state.simulator.tick()
        moving = self.store.snapshot()
        self.assertEqual(moving.revision, recovered_revision + 1)
        self.assertEqual(moving.robots[0].task.status, 'NAVIGATING')
        self.assertNotEqual(moving.robots[0].physical.pose, blocked_pose)

    def test_duplicate_blocked_report_has_no_repeated_side_effect(self):
        self.client.post('/robots/robot-a/blocked', json=self.report)
        revision = self.store.snapshot().revision
        event_count = len(self.store.snapshot().events)

        duplicate = self.client.post('/robots/robot-a/blocked', json=self.report)

        self.assertEqual(duplicate.json(), {'accepted': True})
        self.assertEqual(self.store.snapshot().revision, revision)
        self.assertEqual(len(self.store.snapshot().events), event_count)

    def test_mismatched_and_invalid_blocked_reports_are_rejected(self):
        wrong_session = self.client.post('/robots/robot-a/blocked', json={
            **self.report,
            'session_id': 'old-session',
        })
        unknown_robot = self.client.post('/robots/unknown/blocked', json=self.report)
        wrong_task = self.client.post('/robots/robot-a/blocked', json={
            **self.report,
            'task_id': 'task-other',
        })
        negative_duration = self.client.post('/robots/robot-a/blocked', json={
            **self.report,
            'duration_ms': -1,
        })

        self.assertEqual(wrong_session.status_code, 409)
        self.assertEqual(wrong_session.json()['error']['code'], 'SESSION_MISMATCH')
        self.assertEqual(unknown_robot.status_code, 404)
        self.assertEqual(unknown_robot.json()['error']['code'], 'NOT_FOUND')
        self.assertEqual(wrong_task.status_code, 409)
        self.assertEqual(wrong_task.json()['error']['code'], 'TASK_MISMATCH')
        self.assertEqual(negative_duration.status_code, 422)

    def test_blocked_report_rejects_non_navigation_activity(self):
        activity_store = WorldStore()
        activity_client = TestClient(create_app(world_store=activity_store))
        self.addCleanup(activity_client.close)
        activity_client.post('/game/start')
        task = activity_client.post('/tasks', json={
            'request_id': 'active-task',
            'robot_id': 'robot-a',
            'action': 'FISH',
            'location': 'lake',
        }).json()
        activity_client.post('/robots/robot-a/arrived', json={
            'session_id': activity_store.snapshot().session_id,
            'task_id': task['id'],
            'location': 'lake',
        }).raise_for_status()

        response = activity_client.post('/robots/robot-a/blocked', json={
            'session_id': activity_store.snapshot().session_id,
            'task_id': task['id'],
            'reason': 'not a navigation obstruction',
            'duration_ms': 0,
        })

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'TASK_MISMATCH')


if __name__ == '__main__':
    unittest.main()
