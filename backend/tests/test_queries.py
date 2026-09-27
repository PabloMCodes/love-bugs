import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.simulation.simulator import SimulationRunner
from app.state import WorldStore


class QueryRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = WorldStore()
        self.client = TestClient(create_app(world_store=self.store))

    def tearDown(self):
        self.client.close()

    def assign(
        self,
        request_id,
        robot_id='robot-a',
        action='MOVE_TO',
        location='farm',
        parameters=None,
    ):
        response = self.client.post('/tasks', json={
            'request_id': request_id,
            'robot_id': robot_id,
            'action': action,
            'location': location,
            'parameters': parameters or {},
        })
        self.assertEqual(response.status_code, 202)
        return response.json()

    def test_robot_and_market_queries_match_world(self):
        world = self.client.get('/world').json()

        robots = self.client.get('/robots')
        billy = self.client.get('/robots/robot-a')
        market = self.client.get('/market')
        missing = self.client.get('/robots/missing')

        self.assertEqual(robots.status_code, 200)
        self.assertEqual(robots.json(), {'robots': world['robots']})
        self.assertEqual(billy.json(), world['robots'][0])
        self.assertEqual(market.json(), world['market'])
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()['error']['code'], 'NOT_FOUND')

    def test_task_queries_include_active_and_completed_tasks_in_creation_order(self):
        self.client.post('/game/start').raise_for_status()
        first = self.assign('query-move-a')
        second = self.assign('query-move-b', robot_id='robot-b')

        active = self.client.get('/tasks')
        self.assertEqual(
            [task['id'] for task in active.json()['tasks']],
            [first['id'], second['id']],
        )
        self.assertEqual(
            self.client.get(f"/tasks/{first['id']}").json()['status'],
            'ASSIGNED',
        )

        SimulationRunner(self.store, step_distance=100).tick()
        completed = self.client.get('/tasks').json()['tasks']

        self.assertEqual([task['status'] for task in completed], ['COMPLETED', 'COMPLETED'])
        self.assertTrue(all(task['progress'] == 1 for task in completed))
        self.assertTrue(all(robot.task is None for robot in self.store.snapshot().robots))

    def test_task_query_tracks_activity_progress_and_cancellation(self):
        self.client.post('/game/start').raise_for_status()
        fishing = self.assign(
            'query-fishing',
            action='FISH',
            location='lake',
        )
        simulator = SimulationRunner(
            self.store,
            interval_seconds=.25,
            step_distance=100,
        )
        simulator.tick()
        simulator.tick()

        active = self.client.get(f"/tasks/{fishing['id']}").json()
        self.assertEqual(active['status'], 'ACTIVE')
        self.assertGreater(active['progress'], 0)

        self.client.post('/robots/robot-a/stop').raise_for_status()
        cancelled = self.client.get(f"/tasks/{fishing['id']}").json()
        self.assertEqual(cancelled['status'], 'CANCELLED')
        self.assertEqual(cancelled['progress'], active['progress'])

    def test_task_query_tracks_execution_failure(self):
        self.client.post('/game/start').raise_for_status()
        first = self.assign(
            'query-buy-a',
            action='BUY',
            location='market',
            parameters={'item': 'tool_upgrade', 'quantity': 1},
        )
        second = self.assign(
            'query-buy-b',
            robot_id='robot-b',
            action='BUY',
            location='market',
            parameters={'item': 'tool_upgrade', 'quantity': 1},
        )

        SimulationRunner(self.store, step_distance=100).tick()
        completed = self.client.get(f"/tasks/{first['id']}").json()
        failed = self.client.get(f"/tasks/{second['id']}").json()

        self.assertEqual(completed['status'], 'COMPLETED')
        self.assertEqual(failed['status'], 'FAILED')
        self.assertEqual(failed['error']['code'], 'OUT_OF_STOCK')
        self.assertIn('could not complete the purchase', failed['error']['message'])

    def test_reset_clears_current_session_task_queries(self):
        self.client.post('/game/start').raise_for_status()
        task = self.assign('query-before-reset')

        self.client.post('/game/reset').raise_for_status()

        self.assertEqual(self.client.get('/tasks').json(), {'tasks': []})
        missing = self.client.get(f"/tasks/{task['id']}")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()['error']['code'], 'NOT_FOUND')


if __name__ == '__main__':
    unittest.main()
