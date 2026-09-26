"""Thread-safe ownership of the authoritative in-memory world snapshot."""

from datetime import datetime, timezone
import math
from threading import RLock

from app.game.market import (
    MarketRuleError,
    apply_purchase,
    apply_sale,
    quote_purchase,
    quote_sale,
)
from app.game.tasks import activity_for
from app.schemas import NavigationStep, PoseReport, RobotTask, TaskRequest, WorldSnapshot


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

    def update_pose(self, robot_id: str, report: PoseReport) -> bool:
        with self._lock:
            if report.session_id != self._world.session_id:
                raise WorldStateError(
                    'SESSION_MISMATCH',
                    'The pose report belongs to a different game session.',
                )

            robot = next(
                (candidate for candidate in self._world.robots if candidate.id == robot_id),
                None,
            )
            if robot is None:
                raise WorldStateError('NOT_FOUND', f'Unknown robot {robot_id!r}.')
            if (
                robot.physical.pose_updated_at is not None
                and report.timestamp <= robot.physical.pose_updated_at
            ):
                return False
            if (
                not math.isfinite(report.pose.x)
                or not math.isfinite(report.pose.y)
                or report.pose.x < 0
                or report.pose.x > self._world.map.width
                or report.pose.y < 0
                or report.pose.y > self._world.map.height
            ):
                raise WorldStateError(
                    'INVALID_REQUEST',
                    'Pose coordinates must be finite and inside the configured map.',
                )

            now = datetime.now(timezone.utc)
            world = self._world.model_dump(mode='python')
            robot_data = next(item for item in world['robots'] if item['id'] == robot_id)
            robot_data['physical']['pose'] = report.pose.model_dump(mode='python')
            robot_data['physical']['pose_updated_at'] = report.timestamp
            robot_data['physical']['tracking'] = 'TRACKED'
            world['revision'] += 1
            world['updated_at'] = now
            self._world = WorldSnapshot.model_validate(world)
            return True

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

    def assign_task(self, request: TaskRequest) -> RobotTask:
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

            activity = activity_for(request.action)
            if request.action not in ('MOVE_TO', 'BUY', 'SELL') and activity is None:
                raise WorldStateError(
                    'INVALID_REQUEST',
                    'Only MOVE_TO, HARVEST, FISH, BUY, and SELL are implemented by the backend task service.',
                )
            if request.action not in ('BUY', 'SELL') and request.parameters:
                raise WorldStateError(
                    'INVALID_REQUEST',
                    f'{request.action} does not accept parameters.',
                )
            if self._world.game.status != 'RUNNING':
                raise WorldStateError('GAME_NOT_RUNNING', 'Start the game before assigning tasks.')
            if request.location not in self._world.map.locations:
                raise WorldStateError('NOT_FOUND', f'Unknown destination {request.location!r}.')
            if activity is not None and request.location != activity.location:
                raise WorldStateError(
                    'INVALID_REQUEST',
                    f'{request.action} must take place at {activity.location}.',
                )
            if request.action in ('BUY', 'SELL') and request.location != 'market':
                raise WorldStateError(
                    'INVALID_REQUEST',
                    f'{request.action} must take place at market.',
                )

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
            if request.action in ('BUY', 'SELL'):
                try:
                    if request.action == 'BUY':
                        quote_purchase(
                            robot.game.model_dump(mode='python'),
                            self._world.market.model_dump(mode='python'),
                            request.parameters,
                        )
                    else:
                        quote_sale(robot.game.model_dump(mode='python'), request.parameters)
                except MarketRuleError as error:
                    raise WorldStateError(error.code, error.message) from error

            now = datetime.now(timezone.utc)
            next_revision = self._world.revision + 1
            task = RobotTask(
                id=f'task-{next_revision}',
                robot_id=robot.id,
                action=request.action,
                location=request.location,
                status='ASSIGNED',
                progress=0,
                parameters=request.parameters,
                reason=request.reason or (
                    f'Travel to {request.location}.'
                    if request.action == 'MOVE_TO'
                    else (
                        f'Begin {activity.label} at {request.location}.'
                        if activity is not None
                        else f'{request.action.title()} an item at market.'
                    )
                ),
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
                'message': (
                    f'{robot.name} was assigned to travel to {request.location}.'
                    if request.action == 'MOVE_TO'
                    else (
                        f'{robot.name} was assigned to {activity.label} at {request.location}.'
                        if activity is not None
                        else (
                            f'{robot.name} was assigned to '
                            f'{request.action.lower()} an item at market.'
                        )
                    )
                ),
                'data': {},
            })
            world['events'] = world['events'][-100:]
            self._world = WorldSnapshot.model_validate(world)
            self._task_requests[request.request_id] = (
                request.model_copy(deep=True),
                task.model_copy(deep=True),
            )
            return task.model_copy(deep=True)

    def assign_move_task(self, request: TaskRequest) -> RobotTask:
        """Compatibility alias for callers created before activity tasks existed."""
        return self.assign_task(request)

    def apply_navigation_steps(self, steps: list[NavigationStep]) -> WorldSnapshot:
        with self._lock:
            if not steps:
                return self._world.model_copy(deep=True)

            now = datetime.now(timezone.utc)
            world = self._world.model_dump(mode='python')
            changed = False

            for step in steps:
                robot = next(
                    (item for item in world['robots'] if item['id'] == step.robot_id),
                    None,
                )
                if robot is None:
                    continue

                task = robot['task']
                physical = robot['physical']
                if (
                    task is None
                    or task['id'] != step.task_id
                    or (
                        task['action'] not in ('MOVE_TO', 'BUY', 'SELL')
                        and activity_for(task['action']) is None
                    )
                    or task['status'] not in ('ASSIGNED', 'NAVIGATING')
                    or task['location'] != step.location
                    or not physical['online']
                    or physical['stopped']
                    or physical['blocked']
                    or physical['tracking'] != 'TRACKED'
                ):
                    continue

                physical['pose'] = step.pose.model_dump(mode='python')
                physical['pose_updated_at'] = now
                changed = True

                if step.arrived:
                    robot['game']['location'] = step.location
                    world['events'].append({
                        'id': f"event-{task['id']}-arrived",
                        'timestamp': now,
                        'type': 'robot_arrived',
                        'robot_id': robot['id'],
                        'task_id': task['id'],
                        'message': f"{robot['name']} arrived at {step.location}.",
                        'data': {},
                    })
                    activity = activity_for(task['action'])
                    if task['action'] == 'BUY':
                        self._complete_purchase(world, robot, task, now)
                    elif task['action'] == 'SELL':
                        self._complete_sale(world, robot, task, now)
                    elif activity is None:
                        robot['task'] = None
                    else:
                        task['status'] = 'ACTIVE'
                        task['progress'] = 0
                        world['events'].append({
                            'id': f"event-{task['id']}-started",
                            'timestamp': now,
                            'type': 'task_started',
                            'robot_id': robot['id'],
                            'task_id': task['id'],
                            'message': f"{robot['name']} started {activity.label}.",
                            'data': {},
                        })
                else:
                    robot['game']['location'] = None
                    task['status'] = 'NAVIGATING'

            if not changed:
                return self._world.model_copy(deep=True)

            world['revision'] += 1
            world['updated_at'] = now
            world['events'] = world['events'][-100:]
            self._world = WorldSnapshot.model_validate(world)
            return self._world.model_copy(deep=True)

    def _complete_purchase(self, world: dict, robot: dict, task: dict, now: datetime) -> None:
        try:
            quote = apply_purchase(robot['game'], world['market'], task['parameters'])
        except MarketRuleError as error:
            robot['task'] = None
            world['events'].append({
                'id': f"event-{task['id']}-failed",
                'timestamp': now,
                'type': 'task_failed',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} could not complete the purchase: {error.message}",
                'data': {'code': error.code},
            })
            return

        inventory_quantity = robot['game']['inventory'][quote.item_id]['quantity']
        market_item = next(
            item for item in world['market']['items'] if item['id'] == quote.item_id
        )
        robot['task'] = None
        world['game']['goal']['current'] = sum(
            item['game']['money'] for item in world['robots']
        )
        purchase_events = [
            {
                'id': f"event-{task['id']}-inventory",
                'timestamp': now,
                'type': 'inventory_updated',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} received {quote.quantity} {quote.item_name}.",
                'data': {
                    'item': quote.item_id,
                    'quantity': quote.quantity,
                    'total_quantity': inventory_quantity,
                },
            },
            {
                'id': f"event-{task['id']}-gold",
                'timestamp': now,
                'type': 'gold_updated',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} spent {quote.cost} gold.",
                'data': {
                    'spending': quote.cost,
                    'balance': robot['game']['money'],
                },
            },
        ]
        if market_item['stock'] is not None:
            purchase_events.append({
                'id': f"event-{task['id']}-market",
                'timestamp': now,
                'type': 'market_updated',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f'{quote.item_name} market stock was updated.',
                'data': {
                    'item': quote.item_id,
                    'stock': market_item['stock'],
                },
            })
        purchase_events.append({
            'id': f"event-{task['id']}-completed",
            'timestamp': now,
            'type': 'task_completed',
            'robot_id': robot['id'],
            'task_id': task['id'],
            'message': f"{robot['name']} completed the purchase.",
            'data': {},
        })
        world['events'].extend(purchase_events)

    def _complete_sale(self, world: dict, robot: dict, task: dict, now: datetime) -> None:
        try:
            quote = apply_sale(robot['game'], task['parameters'])
        except MarketRuleError as error:
            robot['task'] = None
            world['events'].append({
                'id': f"event-{task['id']}-failed",
                'timestamp': now,
                'type': 'task_failed',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} could not complete the sale: {error.message}",
                'data': {'code': error.code},
            })
            return

        remaining = robot['game']['inventory'].get(quote.item_id, {}).get('quantity', 0)
        robot['task'] = None
        current_gold = sum(item['game']['money'] for item in world['robots'])
        world['game']['goal']['current'] = current_gold
        world['events'].extend([
            {
                'id': f"event-{task['id']}-inventory",
                'timestamp': now,
                'type': 'inventory_updated',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} sold {quote.quantity} {quote.item_name}.",
                'data': {
                    'item': quote.item_id,
                    'quantity': -quote.quantity,
                    'total_quantity': remaining,
                },
            },
            {
                'id': f"event-{task['id']}-gold",
                'timestamp': now,
                'type': 'gold_updated',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} earned {quote.earnings} gold.",
                'data': {
                    'earnings': quote.earnings,
                    'balance': robot['game']['money'],
                },
            },
            {
                'id': f"event-{task['id']}-completed",
                'timestamp': now,
                'type': 'task_completed',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} completed the sale.",
                'data': {},
            },
        ])

        if current_gold < world['game']['goal']['target']:
            return

        world['game']['status'] = 'COMPLETED'
        for other_robot in world['robots']:
            other_task = other_robot['task']
            if other_task is None:
                continue
            other_robot['task'] = None
            world['events'].append({
                'id': f"event-{other_task['id']}-cancelled",
                'timestamp': now,
                'type': 'task_cancelled',
                'robot_id': other_robot['id'],
                'task_id': other_task['id'],
                'message': f"{other_robot['name']}'s task was cancelled because the goal was reached.",
                'data': {},
            })
        world['events'].append({
            'id': f"event-{task['id']}-goal",
            'timestamp': now,
            'type': 'game_completed',
            'robot_id': robot['id'],
            'task_id': task['id'],
            'message': f'The crew reached {current_gold} gold and completed the goal.',
            'data': {},
        })

    def advance_activities(self, elapsed_seconds: float) -> WorldSnapshot:
        if not math.isfinite(elapsed_seconds) or elapsed_seconds <= 0:
            raise ValueError('elapsed_seconds must be a positive finite number')

        with self._lock:
            if self._world.game.status != 'RUNNING':
                return self._world.model_copy(deep=True)

            now = datetime.now(timezone.utc)
            world = self._world.model_dump(mode='python')
            changed = False

            for robot in world['robots']:
                task = robot['task']
                physical = robot['physical']
                if (
                    task is None
                    or task['status'] != 'ACTIVE'
                    or not physical['online']
                    or physical['stopped']
                    or physical['blocked']
                ):
                    continue

                activity = activity_for(task['action'])
                if activity is None or robot['game']['location'] != activity.location:
                    continue

                progress = min(
                    1,
                    task['progress'] + elapsed_seconds / activity.duration_seconds,
                )
                task['progress'] = progress
                changed = True

                if progress < 1 - 1e-9:
                    continue

                inventory = robot['game']['inventory']
                current_item = inventory.get(activity.item_id)
                total_quantity = (
                    current_item['quantity'] if current_item is not None else 0
                ) + activity.quantity
                inventory[activity.item_id] = {
                    'name': current_item['name'] if current_item is not None else activity.item_name,
                    'quantity': total_quantity,
                    'sell_price': (
                        current_item['sell_price']
                        if current_item is not None
                        else activity.sell_price
                    ),
                }
                robot['task'] = None
                world['events'].extend([
                    {
                        'id': f"event-{task['id']}-inventory",
                        'timestamp': now,
                        'type': 'inventory_updated',
                        'robot_id': robot['id'],
                        'task_id': task['id'],
                        'message': (
                            f"{robot['name']} collected {activity.quantity} "
                            f'{activity.item_name}.'
                        ),
                        'data': {
                            'item': activity.item_id,
                            'quantity': activity.quantity,
                            'total_quantity': total_quantity,
                        },
                    },
                    {
                        'id': f"event-{task['id']}-completed",
                        'timestamp': now,
                        'type': 'task_completed',
                        'robot_id': robot['id'],
                        'task_id': task['id'],
                        'message': f"{robot['name']} completed {activity.label}.",
                        'data': {},
                    },
                ])

            if not changed:
                return self._world.model_copy(deep=True)

            world['revision'] += 1
            world['updated_at'] = now
            world['events'] = world['events'][-100:]
            self._world = WorldSnapshot.model_validate(world)
            return self._world.model_copy(deep=True)
