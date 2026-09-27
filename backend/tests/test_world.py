import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.schemas import WorldSnapshot
from app.state import WorldStore, default_world


class WorldRouteTests(unittest.TestCase):
    def test_world_returns_complete_snapshot(self):
        with TestClient(create_app(world_store=WorldStore())) as client:
            response = client.get('/world')

        self.assertEqual(response.status_code, 200)
        world = response.json()
        self.assertEqual(world['schema_version'], 2)
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
        self.assertEqual(world['farm']['crops'], [{
            'id': 'wheat',
            'name': 'Wheat',
            'seed_item_id': 'seeds',
            'grow_seconds': 8.0,
            'harvest_quantity': 3,
            'sell_price': 12,
            'required_stage': 1,
        }])
        self.assertEqual(world['farm']['plots'], [
            {
                'id': f'plot-{plot_number}',
                'status': 'EMPTY',
                'crop_id': None,
                'planted_by': None,
                'planted_at': None,
                'ready_at': None,
            }
            for plot_number in range(1, 4)
        ])

    def test_snapshots_cannot_mutate_store(self):
        store = WorldStore(default_world())
        snapshot = store.snapshot()
        snapshot.robots[0].name = 'Changed'

        self.assertEqual(store.snapshot().robots[0].name, 'Wall-y')

    def test_nonempty_plot_requires_complete_timing_and_owner_state(self):
        world = default_world()
        world['farm']['plots'][0]['status'] = 'GROWING'
        world['farm']['plots'][0]['crop_id'] = 'wheat'

        with self.assertRaisesRegex(ValidationError, 'complete crop state'):
            WorldSnapshot.model_validate(world)


if __name__ == '__main__':
    unittest.main()
