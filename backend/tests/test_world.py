import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.state import WorldStore, default_world


class WorldRouteTests(unittest.TestCase):
    def test_world_returns_complete_snapshot(self):
        with TestClient(create_app(world_store=WorldStore())) as client:
            response = client.get('/world')

        self.assertEqual(response.status_code, 200)
        world = response.json()
        self.assertEqual(world['schema_version'], 1)
        self.assertEqual([robot['id'] for robot in world['robots']], ['robot-a', 'robot-b'])
        self.assertTrue(all(robot['game']['location'] == 'homebase' for robot in world['robots']))
        self.assertTrue(all(robot['game']['inventory'] == {} for robot in world['robots']))
        self.assertEqual(world['game']['goal'], {
            'type': 'earn_gold',
            'target': 200,
            'current': 80,
        })
        self.assertEqual(world['game']['stage'], 1)
        self.assertEqual(world['market']['items'], [
            {
                'id': 'seeds',
                'name': 'Wheat Seeds',
                'buy_price': 5,
                'sell_price': None,
                'stock': None,
                'required_stage': 1,
                'unlock_at': None,
            },
            {
                'id': 'carrot_seeds',
                'name': 'Carrot Seeds',
                'buy_price': 10,
                'sell_price': None,
                'stock': None,
                'required_stage': 2,
                'unlock_at': 100,
            },
            {
                'id': 'pumpkin_seeds',
                'name': 'Pumpkin Seeds',
                'buy_price': 20,
                'sell_price': None,
                'stock': None,
                'required_stage': 3,
                'unlock_at': 150,
            },
        ])
        self.assertEqual(world['map']['locations']['market'], {'x': 80.0, 'y': 25.0})

    def test_snapshots_cannot_mutate_store(self):
        store = WorldStore(default_world())
        snapshot = store.snapshot()
        snapshot.robots[0].name = 'Changed'

        self.assertEqual(store.snapshot().robots[0].name, 'Wall-y')


if __name__ == '__main__':
    unittest.main()
