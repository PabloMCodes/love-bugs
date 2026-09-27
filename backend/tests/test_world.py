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
        self.assertEqual(world['robots'][1]['game']['inventory']['crop']['quantity'], 3)
        self.assertEqual(world['map']['locations']['market'], {'x': 80.0, 'y': 25.0})

    def test_snapshots_cannot_mutate_store(self):
        store = WorldStore(default_world())
        snapshot = store.snapshot()
        snapshot.robots[0].name = 'Changed'

        self.assertEqual(store.snapshot().robots[0].name, 'Wall-y')


if __name__ == '__main__':
    unittest.main()
