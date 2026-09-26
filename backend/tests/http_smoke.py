"""Exercise the unchanged frontend's API calls against a real local server."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

import httpx
from websockets.sync.client import connect


def main():
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        env = {**os.environ, 'DATABASE_URL': '', 'SQLITE_PATH': str(Path(directory) / 'smoke.sqlite3'),
               'GOOGLE_API_KEY': '', 'GAME_MODE': 'simulation'}
        with open(Path(directory) / 'server.log', 'w+') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
                                       '--host', '127.0.0.1', '--port', str(port)], env=env,
                                      stdout=log, stderr=subprocess.STDOUT)
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10) as client:
                    for _ in range(150):
                        try:
                            client.get('/world').raise_for_status()
                            break
                        except httpx.HTTPError:
                            if server.poll() is not None:
                                raise RuntimeError('Server exited')
                            time.sleep(.1)
                    else:
                        raise RuntimeError('Server startup timed out')
                    world = client.get('/world').json()
                    sid = world['session_id']
                    assert world['map']['locations']['homebase'] == {'x': 50, 'y': 30}
                    goal = client.post('/goal', json={
                        'type': 'earn_gold',
                        'target': 600,
                    })
                    assert goal.json() == {
                        'type': 'earn_gold',
                        'target': 600,
                        'current': 80,
                    }
                    assert client.post('/game/start').status_code == 200

                    def task_done(robot_id):
                        for _ in range(150):
                            current = client.get('/world').json()
                            robot = next(r for r in current['robots'] if r['id'] == robot_id)
                            if robot['task'] is None:
                                return robot
                            time.sleep(.1)
                        raise AssertionError('Task did not finish')

                    for action, params, expected in [('SELL', {'item': 'crop', 'quantity': 1}, 52),
                                                      ('BUY', {'item': 'seeds', 'quantity': 1}, 47)]:
                        request = {'request_id': action, 'robot_id': 'robot-b', 'action': action,
                                   'location': 'market', 'parameters': params}
                        result = client.post('/tasks', json=request)
                        assert result.status_code == 202, result.text
                        assert task_done('robot-b')['game']['money'] == expected
                        revision = client.get('/world').json()['revision']
                        retry = client.post('/tasks', json=request)
                        assert retry.status_code == 202
                        assert retry.json()['id'] == result.json()['id']
                        assert retry.json()['status'] == 'COMPLETED'
                        assert client.get('/world').json()['revision'] == revision
                        assert task_done('robot-b')['game']['money'] == expected
                    request = {'request_id': 'harvest', 'robot_id': 'robot-a', 'action': 'HARVEST', 'location': 'farm'}
                    assert client.post('/tasks', json=request).status_code == 202
                    assert task_done('robot-a')['game']['inventory']['crop']['quantity'] == 3
                    events = client.get('/events').json()['events']
                    assert sum(e['type'] == 'task_completed' for e in events) == 3
                    assert len(client.get('/robots').json()['robots']) == 2
                    assert client.get('/robots/robot-a').json()['id'] == 'robot-a'
                    assert len(client.get('/market').json()['items']) == 3
                    tasks = client.get('/tasks').json()['tasks']
                    assert len(tasks) == 3
                    assert all(task['status'] == 'COMPLETED' for task in tasks)
                    assert client.get(f"/tasks/{tasks[0]['id']}").json() == tasks[0]
                    path = client.get('/robots/robot-a/history').json()
                    assert len(path['position_samples']) > 2
                    assert client.get('/events', params={'session_id': sid}).json()['session_id'] == sid
                    print('PASS goal/world/start/tasks: movement, harvest, sell, buy, query APIs, retry without duplicate reward, persisted history')
                    payload = {'session_id': sid, 'timestamp': (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
                               'pose': {'x': 22, 'y': 50, 'heading': 90}}
                    assert client.post('/robots/robot-a/pose', json=payload).json()['accepted']
                    assert not client.post('/robots/robot-a/pose', json=payload).json()['accepted']
                    assert client.post('/robots/robot-a/health', json={'session_id': sid, 'online': True,
                                                                     'battery': .7, 'blocked': False}).json()['accepted']
                    with connect(f'ws://127.0.0.1:{port}/events', open_timeout=5) as ws:
                        assert json.loads(ws.recv(timeout=5))['data'] == client.get('/world').json()
                    print('PASS pose/health and world WebSocket')
                    response = client.post('/agent-chat/round', json={'world': client.get('/world').json(), 'provider': 'mock'})
                    response.raise_for_status()
                    chat = response.json()
                    assert len(chat['messages']) == 2 and chat['error'] is None
                    assert client.get('/agent-chat').json() == chat
                    with connect(f'ws://127.0.0.1:{port}/agent-chat/events', open_timeout=5) as ws:
                        assert json.loads(ws.recv(timeout=5)) == chat
                    assert client.get('/world', headers={'Origin': 'http://localhost:5173'}).headers['access-control-allow-origin'] == 'http://localhost:5173'
                    print('PASS mock chat GET/POST/WebSocket and frontend CORS')
                    stopped = client.post('/game/stop').json()
                    assert stopped['game']['status'] == 'STOPPED'
                    assert all(robot['physical']['stopped'] for robot in stopped['robots'])
                    restarted = client.post('/game/start').json()
                    assert all(not robot['physical']['stopped'] for robot in restarted['robots'])
                    assert client.post('/robots/robot-a/stop').json()['physical']['stopped']
                    client.post('/game/stop').raise_for_status()
                    restarted = client.post('/game/start').json()
                    assert restarted['robots'][0]['physical']['stopped']
                    assert not restarted['robots'][1]['physical']['stopped']
                    assert not client.post('/robots/robot-a/resume').json()['physical']['stopped']
                    reset = client.post('/game/reset').json()
                    assert reset['session_id'] != sid and reset['revision'] == 1
                    assert reset['game']['status'] == 'READY'
                    assert client.get('/tasks').json() == {'tasks': []}
                    assert client.get('/events', params={'session_id': sid}).status_code == 200
                    print('PASS game stop/start/reset and robot stop/resume lifecycle')
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read())
                raise
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == '__main__':
    main()
