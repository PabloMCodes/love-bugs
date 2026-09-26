"""Run from backend/: PYTHONPATH=. .venv/bin/python tests/http_smoke.py.

Starts a real localhost server with disposable SQLite storage. Uses mock chat;
never calls Gemini or Tiger Data. Stops the server even on assertion failure.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from websockets.sync.client import connect
from app.agents.__main__ import demo_world


def run():
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0))
            port = available.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, DATABASE_URL='', SQLITE_PATH=str(Path(directory) / 'smoke.sqlite3'),
                   GOOGLE_API_KEY='', AGENT_INTERVAL_SECONDS='10', AGENT_TIMEOUT_SECONDS='20')

        def request(path, body=None):
            req = Request(base + path, data=None if body is None else json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json'})
            try:
                response = urlopen(req, timeout=10)
            except HTTPError as error:
                response = error
            with response:
                return response.status, json.load(response)

        def command(world):
            return {'session_id': world['session_id'], 'expected_revision': world['revision']}

        with open(Path(directory) / 'server.log', 'w+') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
                                       '--host', '127.0.0.1', '--port', str(port)],
                                      env=env, stdout=log, stderr=log)
            try:
                for _ in range(200):
                    if server.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    try:
                        status, world = request('/world')
                        assert status == 200
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError('Server did not start')
                print('PASS GET /world')
                status, state = request('/simulation/cooperation/start', command(world))
                assert status == 200 and state['objective']['phase'] == 'ASSIGNED'
                for phase in ['HELP_REQUESTED', 'HELP_ACCEPTED', 'TRAVELING_HOME', 'ONE_ARRIVED', 'BOTH_ARRIVED']:
                    status, state = request('/simulation/cooperation/advance', command(state['world']))
                    assert status == 200 and state['objective']['phase'] == phase
                    assert [r['game']['money'] for r in state['world']['robots']] == [40, 40]
                handoff = command(state['world'])
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(lambda _: request('/simulation/cooperation/advance', handoff), range(2)))
                assert sorted(s for s, _ in results) == [200, 409]
                state = next(body for status, body in results if status == 200)
                assert state['objective']['phase'] == 'COMPLETED'
                assert [r['game']['money'] for r in state['world']['robots']] == [45, 45]
                assert state['world']['game']['goal']['current'] == 90
                status, _ = request('/simulation/cooperation/advance', command(state['world']))
                assert status == 409
                assert request('/world')[1] == state['world']
                print('PASS start/advance; concurrent handoff pays 5 gold each exactly once; repeat rejected')
                status, feed = request('/events')
                assert status == 200 and feed['events'] == state['world']['events']
                assert sum(e['type'] == 'gold_updated' for e in feed['events']) == 2
                assert sum(e['type'] == 'joint_task_completed' for e in feed['events']) == 1
                with connect(base.replace('http:', 'ws:') + '/events', open_timeout=10) as ws:
                    assert json.loads(ws.recv(timeout=10))['data'] == state['world']
                print('PASS GET /events and WS /events')
                # Chat accepts a caller-supplied discussion snapshot; use the existing
                # online mock fixture, not a fabricated hardware connection in /world.
                before_chat = deepcopy(state['world'])
                status, chat = request('/agent-chat/round', {'provider': 'mock', 'world': demo_world()})
                assert status == 200 and chat['mode'] == 'discussion' and chat['provider'] == 'mock'
                assert len(chat['messages']) == 2 and all(m['status'] == 'proposed' for m in chat['messages'])
                assert request('/agent-chat')[1] == chat
                with connect(base.replace('http:', 'ws:') + '/agent-chat/events', open_timeout=10) as ws:
                    assert json.loads(ws.recv(timeout=10))['messages'] == chat['messages']
                assert request('/world')[1] == before_chat
                status, error = request('/agent-chat/round', {'provider': 'invalid', 'world': {}})
                assert status == 422 and 'detail' in error
                print('PASS spectator chat GET/POST/WS; mock proposals do not mutate the order')
                old = command(state['world'])
                status, reset = request('/simulation/cooperation/reset', old)
                assert status == 200 and reset['objective'] is None
                assert reset['world']['session_id'] != old['session_id']
                assert [r['game']['money'] for r in reset['world']['robots']] == [40, 40]
                assert request('/world')[1] == reset['world']
                assert request('/simulation/cooperation/advance', old)[0] == 409
                print('PASS reset; new session, wallets restored, old commands rejected')
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)


if __name__ == '__main__':
    run()
