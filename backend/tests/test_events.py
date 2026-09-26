import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.state import WorldStore


class WorldEventsTests(unittest.TestCase):
    def test_initial_snapshot_and_newer_revision_are_published(self):
        store = WorldStore()

        with TestClient(create_app(world_store=store, run_simulator=False)) as client:
            with client.websocket_connect('/events') as socket:
                initial = socket.receive_json()
                store.start_game()
                updated = socket.receive_json()

        self.assertEqual(initial['type'], 'world_snapshot')
        self.assertEqual(initial['data']['revision'], 1)
        self.assertEqual(len(initial['data']['robots']), 2)
        self.assertEqual(updated['type'], 'world_snapshot')
        self.assertEqual(updated['data']['revision'], 2)
        self.assertEqual(updated['data']['game']['status'], 'RUNNING')

    def test_reconnect_replays_current_snapshot(self):
        store = WorldStore()
        store.start_game()

        with TestClient(create_app(world_store=store, run_simulator=False)) as client:
            with client.websocket_connect('/events') as socket:
                snapshot = socket.receive_json()

        self.assertEqual(snapshot['data']['revision'], store.snapshot().revision)
        self.assertEqual(snapshot['data']['session_id'], store.snapshot().session_id)


if __name__ == '__main__':
    unittest.main()
