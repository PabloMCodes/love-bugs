import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agents.__main__ import demo_world
from app.api.agent_chat import DiscussionService
from app.config import AgentConfig, Settings
from app.main import create_app


class CombinedAppTests(unittest.TestCase):
    def test_both_features_and_their_error_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(database_url=None, sqlite_path=str(Path(directory) / "test.sqlite3"),
                                frontend_origins="http://localhost:5173, http://127.0.0.1:5173")
            service = DiscussionService(AgentConfig(interval_seconds=10))
            with TestClient(create_app(service=service, settings=settings)) as client:
                before = client.get('/world').json()
                response = client.post('/agent-chat/round', json={'provider': 'mock', 'world': demo_world()})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()['messages']), 2)
                self.assertEqual(client.get('/world').json(), before)
                self.assertEqual(client.get('/agent-chat').json(), response.json())
                cooldown = client.post('/agent-chat/round', json={'world': demo_world()})
                self.assertEqual(cooldown.status_code, 429)
                self.assertIn('detail', cooldown.json())
                invalid = client.post('/agent-chat/round', json={'provider': 'invalid', 'world': {}})
                self.assertEqual(invalid.status_code, 422)
                self.assertIn('detail', invalid.json())
                invalid = client.post('/simulation/cooperation/start', json={})
                self.assertEqual(invalid.status_code, 400)
                self.assertEqual(invalid.json()['error']['code'], 'INVALID_REQUEST')
                for route in ('/world', '/agent-chat'):
                    for origin in ('http://localhost:5173', 'http://127.0.0.1:5173'):
                        response = client.get(route, headers={'Origin': origin})
                        self.assertEqual(response.headers['access-control-allow-origin'], origin)
                with client.websocket_connect('/events') as socket:
                    self.assertEqual(socket.receive_json()['data'], before)
                with client.websocket_connect('/agent-chat/events') as socket:
                    self.assertEqual(socket.receive_json()['messages'], service.snapshot()['messages'])

    def test_legacy_factories_and_singular_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(database_url=None, sqlite_path=str(Path(directory) / 'test.sqlite3'),
                                frontend_origin='http://custom.local', frontend_origins=None)
            with TestClient(create_app(settings)) as client:
                self.assertEqual(client.get('/world').status_code, 200)
                self.assertEqual(client.get('/agent-chat').status_code, 200)
                self.assertEqual(client.get('/world', headers={'Origin': 'http://custom.local'}).headers[
                    'access-control-allow-origin'], 'http://custom.local')
            # Original chat create_app(service) still works; isolate its default DB.
            with patch.dict('os.environ', {'DATABASE_URL': '', 'SQLITE_PATH': settings.sqlite_path}):
                with TestClient(create_app(DiscussionService())) as client:
                    self.assertEqual(client.get('/world').status_code, 200)
                    self.assertEqual(client.get('/agent-chat').status_code, 200)
