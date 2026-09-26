"""Thread-safe ownership of the authoritative in-memory world snapshot."""

from datetime import datetime, timezone
from threading import RLock

from app.schemas import RobotTask, TaskRequest, WorldSnapshot


class WorldStateError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


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
        self._task_requests: dict[str, tuple[TaskRequest, RobotTask]] = {}

    def snapshot(self) -> WorldSnapshot:
        with self._lock:
            return self._world.model_copy(deep=True)

    def start_game(self) -> WorldSnapshot:
        with self._lock:
            if self._world.game.status == 'RUNNING':
                return self._world.model_copy(deep=True)
            if self._world.game.status == 'COMPLETED':
                raise WorldStateError('GAME_COMPLETED', 'Reset the completed game before starting again.')

            now = datetime.now(timezone.utc)
            world = self._world.model_dump(mode='python')
            world['revision'] += 1
            world['updated_at'] = now
            world['game']['status'] = 'RUNNING'
            world['events'].append({
                'id': f"event-game-started-{world['revision']}",
                'timestamp': now,
                'type': 'game_started',
                'robot_id': None,
                'task_id': None,
                'message': 'The game started.',
                'data': {},
            })
            world['events'] = world['events'][-100:]
            self._world = WorldSnapshot.model_validate(world)
            return self._world.model_copy(deep=True)

    def assign_move_task(self, request: TaskRequest) -> RobotTask:
        with self._lock:
            previous = self._task_requests.get(request.request_id)
            if previous:
                previous_request, previous_task = previous
                if previous_request == request:
                    return previous_task.model_copy(deep=True)
                raise WorldStateError(
                    'REQUEST_ID_CONFLICT',
                    f'Request ID {request.request_id!r} was already used for different task data.',
                )

            if request.action != 'MOVE_TO':
                raise WorldStateError(
                    'INVALID_REQUEST',
                    'Only MOVE_TO is implemented by the backend task service.',
                )
            if self._world.game.status != 'RUNNING':
                raise WorldStateError('GAME_NOT_RUNNING', 'Start the game before assigning tasks.')
            if request.location not in self._world.map.locations:
                raise WorldStateError('NOT_FOUND', f'Unknown destination {request.location!r}.')

            robot = next(
                (candidate for candidate in self._world.robots if candidate.id == request.robot_id),
                None,
            )
            if robot is None:
                raise WorldStateError('NOT_FOUND', f'Unknown robot {request.robot_id!r}.')
            if robot.task is not None:
                raise WorldStateError('ROBOT_BUSY', f'{robot.id} already has an active task.')
            if robot.physical.stopped:
                raise WorldStateError('ROBOT_STOPPED', f'{robot.id} is stopped.')
            if (
                not robot.physical.online
                or robot.physical.blocked
                or robot.physical.tracking != 'TRACKED'
                or robot.physical.pose is None
            ):
                raise WorldStateError('ROBOT_UNAVAILABLE', f'{robot.id} is unavailable for navigation.')

            now = datetime.now(timezone.utc)
            next_revision = self._world.revision + 1
            task = RobotTask(
                id=f'task-{next_revision}',
                robot_id=robot.id,
                action='MOVE_TO',
                location=request.location,
                status='ASSIGNED',
                progress=0,
                parameters=request.parameters,
                reason=request.reason or f'Travel to {request.location}.',
                error=None,
            )
            world = self._world.model_dump(mode='python')
            robot_data = next(item for item in world['robots'] if item['id'] == robot.id)
            robot_data['task'] = task.model_dump(mode='python')
            world['revision'] = next_revision
            world['updated_at'] = now
            world['events'].append({
                'id': f'event-{task.id}-assigned',
                'timestamp': now,
                'type': 'task_assigned',
                'robot_id': robot.id,
                'task_id': task.id,
                'message': f'{robot.name} was assigned to travel to {request.location}.',
                'data': {},
            })
            world['events'] = world['events'][-100:]
            self._world = WorldSnapshot.model_validate(world)
            self._task_requests[request.request_id] = (
                request.model_copy(deep=True),
                task.model_copy(deep=True),
            )
            return task.model_copy(deep=True)
