"""Thread-safe ownership of the authoritative in-memory world snapshot."""

from datetime import datetime, timezone
from threading import RLock

from app.schemas import WorldSnapshot


def default_world() -> dict:
    now = datetime.now(timezone.utc)

    return {
        'schema_version': 1,
        'session_id': 'demo-session-001',
        'revision': 1,
        'updated_at': now,
        'mode': 'simulation',
        'game': {
            'status': 'READY',
            'goal': {'type': 'earn_gold', 'target': 500, 'current': 80},
        },
        'map': {
            'width': 100,
            'height': 100,
            'locations': {
                'homebase': {'x': 50, 'y': 30},
                'farm': {'x': 20, 'y': 50},
                'lake': {'x': 12, 'y': 30},
                'market': {'x': 80, 'y': 25},
            },
        },
        'robots': [
            {
                'id': 'robot-a',
                'name': 'Billy',
                'physical': {
                    'online': True,
                    'pose': {'x': 12, 'y': 30, 'heading': 0},
                    'pose_updated_at': now,
                    'tracking': 'TRACKED',
                    'battery': .82,
                    'blocked': False,
                    'stopped': False,
                },
                'game': {
                    'location': 'lake',
                    'money': 40,
                    'inventory': {
                        'fish': {'name': 'Salmon', 'quantity': 2, 'sell_price': 18},
                        'berries': {'name': 'Wild Berries', 'quantity': 4, 'sell_price': 9},
                    },
                },
                'task': None,
            },
            {
                'id': 'robot-b',
                'name': 'Milo',
                'physical': {
                    'online': True,
                    'pose': {'x': 80, 'y': 25, 'heading': 180},
                    'pose_updated_at': now,
                    'tracking': 'TRACKED',
                    'battery': .94,
                    'blocked': False,
                    'stopped': False,
                },
                'game': {
                    'location': 'market',
                    'money': 40,
                    'inventory': {
                        'crop': {'name': 'Wheat', 'quantity': 3, 'sell_price': 12},
                        'corn': {'name': 'Corn', 'quantity': 1, 'sell_price': 15},
                        'wood': {'name': 'Wood', 'quantity': 6, 'sell_price': 6},
                    },
                },
                'task': None,
            },
        ],
        'market': {
            'items': [
                {'id': 'seeds', 'name': 'Wheat Seeds', 'buy_price': 5, 'stock': None},
                {'id': 'corn_seeds', 'name': 'Corn Seeds', 'buy_price': 8, 'stock': None},
                {'id': 'tool_upgrade', 'name': 'Tool Upgrade', 'buy_price': 40, 'stock': 1},
            ],
        },
        'events': [
            {
                'id': 'event-001',
                'timestamp': now,
                'type': 'game_ready',
                'robot_id': None,
                'task_id': None,
                'message': 'Billy is at the lake and Milo is at the market.',
                'data': {},
            },
        ],
    }


class WorldStore:
    def __init__(self, world: dict | WorldSnapshot | None = None):
        self._lock = RLock()
        initial_world = default_world() if world is None else world
        self._world = WorldSnapshot.model_validate(initial_world)

    def snapshot(self) -> WorldSnapshot:
        with self._lock:
            return self._world.model_copy(deep=True)
