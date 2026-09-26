import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.state import WorldStore, default_world


class TaskRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = WorldStore()
        self.client = TestClient(create_app(world_store=self.store))
        self.request = {
            'request_id': 'request-001',
            'robot_id': 'robot-a',
            'action': 'MOVE_TO',
            'location': 'farm',
            'parameters': {},
        }

    def tearDown(self):
        self.client.close()

    def test_game_must_start_before_task_assignment(self):
        response = self.client.post('/tasks', json=self.request)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'GAME_NOT_RUNNING')

    def test_move_task_updates_authoritative_world(self):
        start = self.client.post('/game/start')
        response = self.client.post('/tasks', json=self.request)
        world = self.client.get('/world').json()

        self.assertEqual(start.status_code, 200)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['status'], 'ASSIGNED')
        self.assertEqual(world['game']['status'], 'RUNNING')
        self.assertEqual(world['robots'][0]['game']['location'], 'lake')
        self.assertEqual(world['robots'][0]['task'], response.json())
        self.assertEqual(world['events'][-1]['type'], 'task_assigned')

    def test_identical_request_retry_is_idempotent(self):
        self.client.post('/game/start')
        first = self.client.post('/tasks', json=self.request)
        revision = self.client.get('/world').json()['revision']
        second = self.client.post('/tasks', json=self.request)

        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(self.client.get('/world').json()['revision'], revision)

    def test_request_id_cannot_be_reused_for_different_task(self):
        self.client.post('/game/start')
        self.client.post('/tasks', json=self.request)
        changed = {**self.request, 'location': 'market'}
        response = self.client.post('/tasks', json=changed)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'REQUEST_ID_CONFLICT')

    def test_collection_task_is_accepted_for_its_required_location(self):
        self.client.post('/game/start')
        request = {
            **self.request,
            'request_id': 'request-harvest-001',
            'action': 'HARVEST',
            'location': 'farm',
        }

        response = self.client.post('/tasks', json=request)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['action'], 'HARVEST')
        self.assertEqual(response.json()['status'], 'ASSIGNED')

    def test_return_home_requires_homebase_and_no_parameters(self):
        self.client.post('/game/start')
        request = {
            **self.request,
            'request_id': 'request-return-home',
            'action': 'RETURN_HOME',
            'location': 'homebase',
        }

        accepted = self.client.post('/tasks', json=request)

        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(accepted.json()['action'], 'RETURN_HOME')
        self.assertEqual(accepted.json()['location'], 'homebase')
        self.assertEqual(accepted.json()['reason'], 'Return to homebase.')

        for request_id, updates in (
            ('request-return-wrong-location', {'location': 'farm'}),
            ('request-return-parameters', {'parameters': {'item': 'crop'}}),
        ):
            fresh_store = WorldStore()
            with TestClient(create_app(world_store=fresh_store)) as client:
                client.post('/game/start')
                response = client.post('/tasks', json={
                    **request,
                    'request_id': request_id,
                    **updates,
                })
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()['error']['code'], 'INVALID_REQUEST')

    def test_collection_task_rejects_wrong_location_and_parameters(self):
        self.client.post('/game/start')
        wrong_location = {
            **self.request,
            'request_id': 'request-fish-wrong-location',
            'action': 'FISH',
            'location': 'farm',
        }
        parameters = {
            **self.request,
            'request_id': 'request-harvest-parameters',
            'action': 'HARVEST',
            'parameters': {'item': 'crop'},
        }

        location_response = self.client.post('/tasks', json=wrong_location)
        parameters_response = self.client.post('/tasks', json=parameters)

        self.assertEqual(location_response.status_code, 400)
        self.assertEqual(location_response.json()['error']['code'], 'INVALID_REQUEST')
        self.assertEqual(parameters_response.status_code, 400)
        self.assertEqual(parameters_response.json()['error']['code'], 'INVALID_REQUEST')

    def test_sell_task_validates_inventory_and_parameters(self):
        self.client.post('/game/start')
        request = {
            **self.request,
            'request_id': 'request-sell-001',
            'robot_id': 'robot-b',
            'action': 'SELL',
            'location': 'market',
            'parameters': {'item': 'crop', 'quantity': 2},
        }

        accepted = self.client.post('/tasks', json=request)

        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(accepted.json()['action'], 'SELL')
        self.assertEqual(accepted.json()['parameters'], request['parameters'])

        fresh_store = WorldStore()
        with TestClient(create_app(world_store=fresh_store)) as client:
            client.post('/game/start')
            unavailable = client.post('/tasks', json={
                **request,
                'request_id': 'request-sell-too-many',
                'parameters': {'item': 'crop', 'quantity': 99},
            })
            malformed = client.post('/tasks', json={
                **request,
                'request_id': 'request-sell-malformed',
                'parameters': {'item': 'crop'},
            })

        self.assertEqual(unavailable.status_code, 409)
        self.assertEqual(
            unavailable.json()['error']['code'],
            'INSUFFICIENT_INVENTORY',
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()['error']['code'], 'INVALID_REQUEST')

    def test_buy_task_validates_market_funds_and_stock(self):
        self.client.post('/game/start')
        request = {
            **self.request,
            'request_id': 'request-buy-001',
            'robot_id': 'robot-b',
            'action': 'BUY',
            'location': 'market',
            'parameters': {'item': 'tool_upgrade', 'quantity': 1},
        }

        accepted = self.client.post('/tasks', json=request)

        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(accepted.json()['action'], 'BUY')
        self.assertEqual(accepted.json()['parameters'], request['parameters'])

        funds_store = WorldStore()
        with TestClient(create_app(world_store=funds_store)) as client:
            client.post('/game/start')
            insufficient_funds = client.post('/tasks', json={
                **request,
                'request_id': 'request-buy-expensive',
                'parameters': {'item': 'seeds', 'quantity': 9},
            })
            unknown = client.post('/tasks', json={
                **request,
                'request_id': 'request-buy-unknown',
                'parameters': {'item': 'unknown', 'quantity': 1},
            })

        stocked_world = default_world()
        stocked_world['robots'][1]['game']['money'] = 100
        stock_store = WorldStore(stocked_world)
        with TestClient(create_app(world_store=stock_store)) as client:
            client.post('/game/start')
            out_of_stock = client.post('/tasks', json={
                **request,
                'request_id': 'request-buy-stock',
                'parameters': {'item': 'tool_upgrade', 'quantity': 2},
            })

        self.assertEqual(insufficient_funds.status_code, 409)
        self.assertEqual(
            insufficient_funds.json()['error']['code'],
            'INSUFFICIENT_FUNDS',
        )
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unknown.json()['error']['code'], 'NOT_FOUND')
        self.assertEqual(out_of_stock.status_code, 409)
        self.assertEqual(out_of_stock.json()['error']['code'], 'OUT_OF_STOCK')


if __name__ == '__main__':
    unittest.main()
