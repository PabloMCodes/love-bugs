from datetime import datetime, timedelta, timezone
import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.state import WorldStore, default_world


def ready_wheat_plot(world: dict, plot_index: int = 0) -> str:
    planted_at = datetime.now(timezone.utc) - timedelta(seconds=9)
    plot = world['farm']['plots'][plot_index]
    plot.update({
        'status': 'READY',
        'crop_id': 'wheat',
        'planted_by': 'robot-a',
        'planted_at': planted_at,
        'ready_at': planted_at + timedelta(seconds=8),
    })
    return plot['id']


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
        self.assertEqual(world['robots'][0]['game']['location'], 'homebase')
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
        world = default_world()
        plot_id = ready_wheat_plot(world)
        request = {
            **self.request,
            'request_id': 'request-harvest-001',
            'action': 'HARVEST',
            'location': 'farm',
            'parameters': {'plot_id': plot_id},
        }

        with TestClient(create_app(world_store=WorldStore(world))) as client:
            client.post('/game/start')
            response = client.post('/tasks', json=request)

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
        malformed_parameters = {
            **self.request,
            'request_id': 'request-harvest-parameters',
            'action': 'HARVEST',
            'parameters': {'item': 'crop'},
        }
        not_ready = {
            **self.request,
            'request_id': 'request-harvest-not-ready',
            'action': 'HARVEST',
            'parameters': {'plot_id': 'plot-1'},
        }

        location_response = self.client.post('/tasks', json=wrong_location)
        parameters_response = self.client.post('/tasks', json=malformed_parameters)
        not_ready_response = self.client.post('/tasks', json=not_ready)

        self.assertEqual(location_response.status_code, 400)
        self.assertEqual(location_response.json()['error']['code'], 'INVALID_REQUEST')
        self.assertEqual(parameters_response.status_code, 400)
        self.assertEqual(parameters_response.json()['error']['code'], 'INVALID_REQUEST')
        self.assertEqual(not_ready_response.status_code, 409)
        self.assertEqual(not_ready_response.json()['error']['code'], 'PLOT_NOT_READY')

    def test_plant_task_requires_owned_seed_empty_plot_and_exact_parameters(self):
        self.client.post('/game/start')
        base_request = {
            **self.request,
            'action': 'PLANT',
            'location': 'farm',
            'parameters': {'item': 'seeds', 'plot_id': 'plot-1'},
        }

        no_seed = self.client.post('/tasks', json={
            **base_request,
            'request_id': 'request-plant-no-seed',
        })
        malformed = self.client.post('/tasks', json={
            **base_request,
            'request_id': 'request-plant-malformed',
            'parameters': {'item': 'seeds'},
        })
        self.assertEqual(no_seed.status_code, 409)
        self.assertEqual(no_seed.json()['error']['code'], 'INSUFFICIENT_INVENTORY')
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()['error']['code'], 'INVALID_REQUEST')

        world = default_world()
        world['robots'][0]['game']['inventory']['seeds'] = {
            'name': 'Wheat Seeds',
            'quantity': 1,
            'sell_price': None,
        }
        with TestClient(create_app(world_store=WorldStore(world))) as client:
            client.post('/game/start')
            wrong_location = client.post('/tasks', json={
                **base_request,
                'request_id': 'request-plant-wrong-location',
                'location': 'market',
            })
            unknown_plot = client.post('/tasks', json={
                **base_request,
                'request_id': 'request-plant-unknown-plot',
                'parameters': {'item': 'seeds', 'plot_id': 'plot-99'},
            })
            accepted = client.post('/tasks', json={
                **base_request,
                'request_id': 'request-plant-accepted',
            })

        self.assertEqual(wrong_location.status_code, 400)
        self.assertEqual(wrong_location.json()['error']['code'], 'INVALID_REQUEST')
        self.assertEqual(unknown_plot.status_code, 404)
        self.assertEqual(unknown_plot.json()['error']['code'], 'NOT_FOUND')
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(accepted.json()['action'], 'PLANT')
        self.assertEqual(accepted.json()['parameters'], base_request['parameters'])

    def test_later_crop_planting_requires_its_farm_stage(self):
        world = default_world()
        world['robots'][0]['game']['inventory']['carrot_seeds'] = {
            'name': 'Carrot Seeds',
            'quantity': 1,
            'sell_price': None,
        }
        request = {
            **self.request,
            'request_id': 'request-plant-carrot-locked',
            'action': 'PLANT',
            'location': 'farm',
            'parameters': {'item': 'carrot_seeds', 'plot_id': 'plot-1'},
        }

        with TestClient(create_app(world_store=WorldStore(world))) as client:
            client.post('/game/start')
            locked = client.post('/tasks', json=request)

        self.assertEqual(locked.status_code, 409)
        self.assertEqual(locked.json()['error']['code'], 'SEED_LOCKED')

        world['game']['stage'] = 2
        with TestClient(create_app(world_store=WorldStore(world))) as client:
            client.post('/game/start')
            accepted = client.post('/tasks', json={
                **request,
                'request_id': 'request-plant-carrot-unlocked',
            })

        self.assertEqual(accepted.status_code, 202)

    def test_sell_task_validates_inventory_and_parameters(self):
        world = default_world()
        world['robots'][1]['game']['inventory']['crop'] = {
            'name': 'Wheat',
            'quantity': 3,
            'sell_price': 12,
        }
        request = {
            **self.request,
            'request_id': 'request-sell-001',
            'robot_id': 'robot-b',
            'action': 'SELL',
            'location': 'market',
            'parameters': {'item': 'crop', 'quantity': 2},
        }

        with TestClient(create_app(world_store=WorldStore(world))) as client:
            client.post('/game/start')
            accepted = client.post('/tasks', json=request)

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
        locked = self.client.post('/tasks', json={
            **self.request,
            'request_id': 'request-buy-locked',
            'robot_id': 'robot-a',
            'action': 'BUY',
            'location': 'market',
            'parameters': {'item': 'carrot_seeds', 'quantity': 1},
        })
        request = {
            **self.request,
            'request_id': 'request-buy-001',
            'robot_id': 'robot-b',
            'action': 'BUY',
            'location': 'market',
            'parameters': {'item': 'seeds', 'quantity': 1},
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
        stocked_world['game']['stage'] = 3
        stocked_world['robots'][1]['game']['money'] = 100
        next(
            item for item in stocked_world['market']['items']
            if item['id'] == 'pumpkin_seeds'
        )['stock'] = 1
        stock_store = WorldStore(stocked_world)
        with TestClient(create_app(world_store=stock_store)) as client:
            client.post('/game/start')
            out_of_stock = client.post('/tasks', json={
                **request,
                'request_id': 'request-buy-stock',
                'parameters': {'item': 'pumpkin_seeds', 'quantity': 2},
            })

        self.assertEqual(locked.status_code, 409)
        self.assertEqual(locked.json()['error']['code'], 'SEED_LOCKED')
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
