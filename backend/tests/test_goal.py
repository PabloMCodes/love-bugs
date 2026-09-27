import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.state import WorldStore


class GoalRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = WorldStore()
        self.client = TestClient(create_app(world_store=self.store))

    def tearDown(self):
        self.client.close()

    def test_configures_goal_while_ready(self):
        before = self.client.get('/world').json()

        response = self.client.post('/goal', json={
            'type': 'earn_gold',
            'target': 750,
        })
        world = self.client.get('/world').json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'type': 'earn_gold',
            'target': 750,
            'current': 80,
        })
        self.assertEqual(world['game']['goal'], response.json())
        self.assertEqual(world['revision'], before['revision'] + 1)
        self.assertEqual(world['events'][-1]['type'], 'goal_configured')
        self.assertEqual(world['events'][-1]['data'], response.json())

    def test_identical_goal_configuration_has_no_side_effect(self):
        request = {'type': 'earn_gold', 'target': 750}
        first = self.client.post('/goal', json=request)
        revision = self.store.snapshot().revision

        second = self.client.post('/goal', json=request)

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(self.store.snapshot().revision, revision)

    def test_rejects_goal_change_after_game_starts(self):
        self.client.post('/game/start').raise_for_status()

        response = self.client.post('/goal', json={
            'type': 'earn_gold',
            'target': 750,
        })

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'GAME_NOT_READY')
        self.assertEqual(self.store.snapshot().game.goal.target, 200)

    def test_rejects_target_that_is_already_met(self):
        response = self.client.post('/goal', json={
            'type': 'earn_gold',
            'target': 80,
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'INVALID_REQUEST')
        self.assertEqual(self.store.snapshot().game.goal.target, 200)


if __name__ == '__main__':
    unittest.main()
