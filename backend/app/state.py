"""Thread-safe ownership of the authoritative in-memory world snapshot."""

from datetime import datetime, timezone
import math
from threading import RLock
from uuid import uuid4

from app.game.crops import (
    CropRuleError,
    apply_harvest,
    apply_planting,
    quote_harvest,
    quote_planting,
)
from app.game.market import (
    MarketRuleError,
    apply_purchase,
    apply_sale,
    quote_purchase,
    quote_sale,
)
from app.game.tasks import activity_for
from app.schemas import (
    ArrivalReport,
    BlockedReport,
    Goal,
    GoalRequest,
    HealthReport,
    Market,
    NavigationStep,
    PoseReport,
    Robot,
    RobotTask,
    TaskError,
    TaskRequest,
    WorldSnapshot,
)


STAGE_UNLOCKS = (
    (2, 100, 'carrot_seeds', 'Carrot Seeds'),
    (3, 150, 'pumpkin_seeds', 'Pumpkin Seeds'),
)


class WorldStateError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def default_world(mode: str = 'simulation') -> dict:
    if mode not in ('simulation', 'hardware'):
        raise ValueError('mode must be either simulation or hardware')
    now = datetime.now(timezone.utc)

    world = {
        'schema_version': 2,
        'session_id': 'demo-session-001',
        'revision': 1,
        'updated_at': now,
        'mode': mode,
        'game': {
            'status': 'READY',
            'goal': {'type': 'earn_gold', 'target': 200, 'current': 80},
            'stage': 1,
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
                'name': 'Wall-y',
                'physical': {
                    'online': True,
                    'pose': {'x': 50, 'y': 30, 'heading': 0},
                    'pose_updated_at': now,
                    'tracking': 'TRACKED',
                    'battery': .82,
                    'blocked': False,
                    'stopped': False,
                },
                'game': {
                    'location': 'homebase',
                    'money': 40,
                    'inventory': {},
                },
                'task': None,
            },
            {
                'id': 'robot-b',
                'name': 'Eeva',
                'physical': {
                    'online': True,
                    'pose': {'x': 50, 'y': 30, 'heading': 180},
                    'pose_updated_at': now,
                    'tracking': 'TRACKED',
                    'battery': .94,
                    'blocked': False,
                    'stopped': False,
                },
                'game': {
                    'location': 'homebase',
                    'money': 40,
                    'inventory': {},
                },
                'task': None,
            },
        ],
        'market': {
            'items': [
                {
                    'id': 'seeds', 'name': 'Wheat Seeds', 'buy_price': 5,
                    'stock': None, 'required_stage': 1, 'unlock_at': None,
                },
                {
                    'id': 'carrot_seeds', 'name': 'Carrot Seeds', 'buy_price': 10,
                    'stock': None, 'required_stage': 2, 'unlock_at': 100,
                },
                {
                    'id': 'pumpkin_seeds', 'name': 'Pumpkin Seeds', 'buy_price': 20,
                    'stock': None, 'required_stage': 3, 'unlock_at': 150,
                },
            ],
        },
        'farm': {
            'crops': [
                {
                    'id': 'wheat',
                    'name': 'Wheat',
                    'seed_item_id': 'seeds',
                    'grow_seconds': 8,
                    'harvest_quantity': 3,
                    'sell_price': 12,
                    'required_stage': 1,
                },
            ],
            'plots': [
                {
                    'id': f'plot-{plot_number}',
                    'status': 'EMPTY',
                    'crop_id': None,
                    'planted_by': None,
                    'planted_at': None,
                    'ready_at': None,
                }
                for plot_number in range(1, 4)
            ],
        },
        'events': [
            {
                'id': 'event-001',
                'timestamp': now,
                'type': 'game_ready',
                'robot_id': None,
                'task_id': None,
                'message': 'Wall-y and Eeva are at homebase, ready to begin.',
                'data': {},
            },
        ],
    }

    if mode == 'hardware':
        for robot in world['robots']:
            robot['physical'].update({
                'online': False,
                'pose': None,
                'pose_updated_at': None,
                'tracking': 'UNKNOWN',
                'battery': None,
                'blocked': False,
            })
            robot['game']['location'] = None
        world['events'][0]['message'] = (
            'Hardware mode is ready and waiting for robot telemetry.'
        )

    return world


class WorldStore:
    def __init__(self, world: dict | WorldSnapshot | None = None):
        self._lock = RLock()
        initial_world = default_world() if world is None else world
        self._world = WorldSnapshot.model_validate(initial_world)
        self._initial_world = self._world.model_copy(deep=True)
        self._tasks: dict[str, RobotTask] = {
            robot.task.id: robot.task.model_copy(deep=True)
            for robot in self._world.robots
            if robot.task is not None
        }
        self._task_requests: dict[str, tuple[TaskRequest, RobotTask]] = {}
        self._accepted_arrivals: dict[tuple[str, str, str], str] = {}
        self._health_seen_at: dict[str, datetime] = {}
        self._pose_seen_at: dict[str, datetime] = {}
        self._robot_stop_requests: set[str] = set()
        self._recorder = None

    def attach_recorder(self, recorder):
        """Attach history before serving requests; persist the initial snapshot."""
        with self._lock:
            recorder.record(self._world, None)
            self._recorder = recorder

    def _publish(self, world, *, position_source=None):
        candidate = WorldSnapshot.model_validate(world)
        if self._recorder is not None:
            self._recorder.record(candidate, self._world, position_source=position_source)
        self._world = candidate
        self._sync_task_history(candidate)

    def _sync_task_history(self, world: WorldSnapshot) -> None:
        for robot in world.robots:
            if robot.task is not None:
                self._tasks[robot.task.id] = robot.task.model_copy(deep=True)

        terminal_statuses = {
            'task_completed': 'COMPLETED',
            'task_failed': 'FAILED',
            'task_cancelled': 'CANCELLED',
        }
        for event in world.events:
            status = terminal_statuses.get(event.type)
            if status is None or event.task_id not in self._tasks:
                continue
            task = self._tasks[event.task_id]
            updates = {
                'status': status,
                'progress': 1 if status == 'COMPLETED' else task.progress,
                'error': None,
            }
            if status == 'FAILED':
                updates['error'] = TaskError(
                    code=event.data.get('code', 'TASK_FAILED'),
                    message=event.message,
                )
            self._tasks[event.task_id] = task.model_copy(update=updates)

        for request_id, (request, task) in self._task_requests.items():
            current = self._tasks.get(task.id)
            if current is not None:
                self._task_requests[request_id] = (
                    request,
                    current.model_copy(deep=True),
                )

    def snapshot(self) -> WorldSnapshot:
        with self._lock:
            return self._world.model_copy(deep=True)

    def robots(self) -> list[Robot]:
        with self._lock:
            return [robot.model_copy(deep=True) for robot in self._world.robots]

    def robot(self, robot_id: str) -> Robot:
        with self._lock:
            robot = next(
                (candidate for candidate in self._world.robots if candidate.id == robot_id),
                None,
            )
            if robot is None:
                raise WorldStateError('NOT_FOUND', f'Unknown robot {robot_id!r}.')
            return robot.model_copy(deep=True)

    def market(self) -> Market:
        with self._lock:
            return self._world.market.model_copy(deep=True)

    def tasks(self) -> list[RobotTask]:
        with self._lock:
            return [task.model_copy(deep=True) for task in self._tasks.values()]

    def task(self, task_id: str) -> RobotTask:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise WorldStateError('NOT_FOUND', f'Unknown task {task_id!r}.')
            return task.model_copy(deep=True)

    def configure_goal(self, request: GoalRequest) -> Goal:
        with self._lock:
            if self._world.game.status != 'READY':
                raise WorldStateError(
                    'GAME_NOT_READY',
                    'The goal can only be changed while the game is ready.',
                )

            current = sum(robot.game.money for robot in self._world.robots)
            if request.target <= current:
                raise WorldStateError(
                    'INVALID_REQUEST',
                    f'The goal target must be greater than the current {current} gold.',
                )

            existing = self._world.game.goal
            if existing.type == request.type and existing.target == request.target:
                return existing.model_copy(deep=True)

            now = datetime.now(timezone.utc)
            world = self._world.model_dump(mode='python')
            world['revision'] += 1
            world['updated_at'] = now
            world['game']['goal'] = {
                'type': request.type,
                'target': request.target,
                'current': current,
            }
            world['events'].append({
                'id': f"event-goal-configured-{world['revision']}",
                'timestamp': now,
                'type': 'goal_configured',
                'robot_id': None,
                'task_id': None,
                'message': f'The crew goal was set to {request.target} gold.',
                'data': {
                    'type': request.type,
                    'target': request.target,
                    'current': current,
                },
            })
            world['events'] = world['events'][-100:]
            self._publish(world)
            return self._world.game.goal.model_copy(deep=True)

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
            self._publish(world, position_source="pose_report")
            self._pose_seen_at[robot_id] = now
            return True

    def update_health(self, robot_id: str, report: HealthReport) -> bool:
        with self._lock:
            if report.session_id != self._world.session_id:
                raise WorldStateError(
                    'SESSION_MISMATCH',
                    'The health report belongs to a different game session.',
                )

            robot = next(
                (candidate for candidate in self._world.robots if candidate.id == robot_id),
                None,
            )
            if robot is None:
                raise WorldStateError('NOT_FOUND', f'Unknown robot {robot_id!r}.')

            now = datetime.now(timezone.utc)
            if (
                robot.physical.online == report.online
                and robot.physical.battery == report.battery
                and robot.physical.blocked == report.blocked
            ):
                self._health_seen_at[robot_id] = now
                return True

            world = self._world.model_dump(mode='python')
            robot_data = next(item for item in world['robots'] if item['id'] == robot_id)
            physical = robot_data['physical']
            events = []

            if physical['online'] != report.online:
                events.append({
                    'id': f"event-health-{world['revision'] + 1}-online",
                    'timestamp': now,
                    'type': 'robot_online' if report.online else 'robot_offline',
                    'robot_id': robot_id,
                    'task_id': robot_data['task']['id'] if robot_data['task'] else None,
                    'message': (
                        f"{robot_data['name']} came online."
                        if report.online
                        else f"{robot_data['name']} went offline."
                    ),
                    'data': {'online': report.online},
                })
            if physical['blocked'] != report.blocked:
                events.append({
                    'id': f"event-health-{world['revision'] + 1}-blocked",
                    'timestamp': now,
                    'type': 'robot_blocked' if report.blocked else 'robot_unblocked',
                    'robot_id': robot_id,
                    'task_id': robot_data['task']['id'] if robot_data['task'] else None,
                    'message': (
                        f"{robot_data['name']} reported blocked movement."
                        if report.blocked
                        else f"{robot_data['name']} is no longer blocked."
                    ),
                    'data': {'blocked': report.blocked},
                })

            physical['online'] = report.online
            physical['battery'] = report.battery
            physical['blocked'] = report.blocked
            world['revision'] += 1
            world['updated_at'] = now
            world['events'] = (world['events'] + events)[-100:]
            self._publish(world)
            self._health_seen_at[robot_id] = now
            return True

    def expire_stale_telemetry(
        self,
        checked_at: datetime,
        *,
        health_timeout_seconds: float,
        pose_timeout_seconds: float,
    ) -> WorldSnapshot:
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError('checked_at must include a timezone')
        if any(
            not math.isfinite(value) or value <= 0
            for value in (health_timeout_seconds, pose_timeout_seconds)
        ):
            raise ValueError('Telemetry timeouts must be positive finite numbers')

        with self._lock:
            if self._world.mode != 'hardware':
                return self._world.model_copy(deep=True)

            world = self._world.model_dump(mode='python')
            events = []
            next_revision = world['revision'] + 1
            for robot in world['robots']:
                robot_id = robot['id']
                task_id = robot['task']['id'] if robot['task'] else None
                health_seen_at = self._health_seen_at.get(robot_id)
                if (
                    robot['physical']['online']
                    and health_seen_at is not None
                    and (checked_at - health_seen_at).total_seconds()
                    >= health_timeout_seconds
                ):
                    robot['physical']['online'] = False
                    events.append({
                        'id': f'event-telemetry-{next_revision}-{robot_id}-offline',
                        'timestamp': checked_at,
                        'type': 'robot_offline',
                        'robot_id': robot_id,
                        'task_id': task_id,
                        'message': f"{robot['name']} went offline after missing health reports.",
                        'data': {'reason': 'health_timeout'},
                    })

                pose_seen_at = self._pose_seen_at.get(robot_id)
                if (
                    robot['physical']['tracking'] == 'TRACKED'
                    and pose_seen_at is not None
                    and (checked_at - pose_seen_at).total_seconds()
                    >= pose_timeout_seconds
                ):
                    robot['physical']['tracking'] = 'STALE'
                    events.append({
                        'id': f'event-telemetry-{next_revision}-{robot_id}-tracking',
                        'timestamp': checked_at,
                        'type': 'tracking_stale',
                        'robot_id': robot_id,
                        'task_id': task_id,
                        'message': f"{robot['name']}'s tracking became stale.",
                        'data': {'reason': 'pose_timeout'},
                    })

            if not events:
                return self._world.model_copy(deep=True)

            world['revision'] = next_revision
            world['updated_at'] = checked_at
            world['events'] = (world['events'] + events)[-100:]
            self._publish(world)
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
            for robot in world['robots']:
                if robot['id'] not in self._robot_stop_requests:
                    robot['physical']['stopped'] = False
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
            self._publish(world)
            return self._world.model_copy(deep=True)

    def stop_game(self) -> WorldSnapshot:
        with self._lock:
            target_status = (
                'COMPLETED'
                if self._world.game.status == 'COMPLETED'
                else 'STOPPED'
            )
            if (
                self._world.game.status == target_status
                and all(
                    robot.physical.stopped and robot.task is None
                    for robot in self._world.robots
                )
            ):
                return self._world.model_copy(deep=True)

            now = datetime.now(timezone.utc)
            world = self._world.model_dump(mode='python')
            world['game']['status'] = target_status
            for robot in world['robots']:
                self._cancel_task(world, robot, now, 'the game was stopped')
                robot['physical']['stopped'] = True
            world['revision'] += 1
            world['updated_at'] = now
            world['events'].append({
                'id': f"event-game-stopped-{world['revision']}",
                'timestamp': now,
                'type': 'game_stopped',
                'robot_id': None,
                'task_id': None,
                'message': 'The game was stopped.',
                'data': {},
            })
            world['events'] = world['events'][-100:]
            self._publish(world)
            return self._world.model_copy(deep=True)

    def reset_game(self) -> WorldSnapshot:
        with self._lock:
            self.stop_game()
            now = datetime.now(timezone.utc)
            world = self._initial_world.model_dump(mode='python')
            world['session_id'] = str(uuid4())
            world['revision'] = 1
            world['updated_at'] = now
            world['game']['status'] = 'READY'

            current_robots = {robot.id: robot for robot in self._world.robots}
            home = world['map']['locations'].get('homebase')
            for robot in world['robots']:
                robot['task'] = None
                robot['physical']['stopped'] = True
                if world['mode'] == 'simulation':
                    robot['physical']['blocked'] = False
                    if home is not None:
                        heading = (
                            robot['physical']['pose']['heading']
                            if robot['physical']['pose'] is not None
                            else 0
                        )
                        robot['physical']['pose'] = {
                            'x': home['x'],
                            'y': home['y'],
                            'heading': heading,
                        }
                        robot['physical']['pose_updated_at'] = now
                        robot['physical']['tracking'] = 'TRACKED'
                        robot['game']['location'] = 'homebase'
                else:
                    current = current_robots.get(robot['id'])
                    if current is not None:
                        robot['physical'] = current.physical.model_dump(mode='python')
                        robot['physical']['stopped'] = True
                        robot['physical']['tracking'] = (
                            'STALE'
                            if robot['physical']['pose'] is not None
                            else 'UNKNOWN'
                        )
                    robot['game']['location'] = None

            world['events'] = [{
                'id': 'event-game-ready-1',
                'timestamp': now,
                'type': 'game_ready',
                'robot_id': None,
                'task_id': None,
                'message': 'A new game session is ready.',
                'data': {},
            }]
            self._publish(world, position_source='reset')
            self._tasks.clear()
            self._task_requests.clear()
            self._accepted_arrivals.clear()
            self._health_seen_at.clear()
            self._pose_seen_at.clear()
            self._robot_stop_requests.clear()
            return self._world.model_copy(deep=True)

    def stop_robot(self, robot_id: str) -> Robot:
        with self._lock:
            robot = next(
                (candidate for candidate in self._world.robots if candidate.id == robot_id),
                None,
            )
            if robot is None:
                raise WorldStateError('NOT_FOUND', f'Unknown robot {robot_id!r}.')
            if (
                robot_id in self._robot_stop_requests
                and robot.physical.stopped
                and robot.task is None
            ):
                return robot.model_copy(deep=True)

            now = datetime.now(timezone.utc)
            world = self._world.model_dump(mode='python')
            robot_data = next(item for item in world['robots'] if item['id'] == robot_id)
            self._cancel_task(
                world,
                robot_data,
                now,
                'the robot was stopped',
            )
            robot_data['physical']['stopped'] = True
            world['revision'] += 1
            world['updated_at'] = now
            world['events'].append({
                'id': f"event-{robot_id}-stopped-{world['revision']}",
                'timestamp': now,
                'type': 'robot_stopped',
                'robot_id': robot_id,
                'task_id': None,
                'message': f"{robot_data['name']} was stopped.",
                'data': {},
            })
            world['events'] = world['events'][-100:]
            self._publish(world)
            self._robot_stop_requests.add(robot_id)
            return next(
                candidate.model_copy(deep=True)
                for candidate in self._world.robots
                if candidate.id == robot_id
            )

    def resume_robot(self, robot_id: str) -> Robot:
        with self._lock:
            robot = next(
                (candidate for candidate in self._world.robots if candidate.id == robot_id),
                None,
            )
            if robot is None:
                raise WorldStateError('NOT_FOUND', f'Unknown robot {robot_id!r}.')
            if self._world.game.status != 'RUNNING':
                raise WorldStateError(
                    'GAME_NOT_RUNNING',
                    'Start the game before resuming a robot.',
                )
            if (
                not robot.physical.online
                or robot.physical.blocked
                or robot.physical.tracking != 'TRACKED'
                or robot.physical.pose is None
            ):
                raise WorldStateError(
                    'ROBOT_UNAVAILABLE',
                    f'{robot.id} is unavailable for navigation.',
                )
            if not robot.physical.stopped:
                self._robot_stop_requests.discard(robot_id)
                return robot.model_copy(deep=True)

            now = datetime.now(timezone.utc)
            world = self._world.model_dump(mode='python')
            robot_data = next(item for item in world['robots'] if item['id'] == robot_id)
            robot_data['physical']['stopped'] = False
            world['revision'] += 1
            world['updated_at'] = now
            world['events'].append({
                'id': f"event-{robot_id}-resumed-{world['revision']}",
                'timestamp': now,
                'type': 'robot_resumed',
                'robot_id': robot_id,
                'task_id': None,
                'message': f"{robot_data['name']} was resumed.",
                'data': {},
            })
            world['events'] = world['events'][-100:]
            self._publish(world)
            self._robot_stop_requests.discard(robot_id)
            return next(
                candidate.model_copy(deep=True)
                for candidate in self._world.robots
                if candidate.id == robot_id
            )

    def _cancel_task(
        self,
        world: dict,
        robot: dict,
        now: datetime,
        reason: str,
    ) -> str | None:
        task = robot['task']
        if task is None:
            return None
        robot['task'] = None
        world['events'].append({
            'id': f"event-{task['id']}-cancelled",
            'timestamp': now,
            'type': 'task_cancelled',
            'robot_id': robot['id'],
            'task_id': task['id'],
            'message': f"{robot['name']}'s task was cancelled because {reason}.",
            'data': {},
        })
        return task['id']

    def assign_task(
        self,
        request: TaskRequest,
        *,
        agent_decision: bool = False,
    ) -> RobotTask:
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
            if request.action not in ('MOVE_TO', 'RETURN_HOME', 'BUY', 'SELL', 'PLANT') and activity is None:
                raise WorldStateError(
                    'INVALID_REQUEST',
                    'Only MOVE_TO, RETURN_HOME, HARVEST, FISH, BUY, SELL, and PLANT are implemented by the backend task service.',
                )
            if request.action not in ('BUY', 'SELL', 'PLANT', 'HARVEST') and request.parameters:
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
            if request.action == 'RETURN_HOME' and request.location != 'homebase':
                raise WorldStateError(
                    'INVALID_REQUEST',
                    'RETURN_HOME must use the homebase destination.',
                )
            if request.action in ('BUY', 'SELL') and request.location != 'market':
                raise WorldStateError(
                    'INVALID_REQUEST',
                    f'{request.action} must take place at market.',
                )
            if request.action == 'PLANT' and request.location != 'farm':
                raise WorldStateError(
                    'INVALID_REQUEST',
                    'PLANT must take place at farm.',
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
                            current_stage=self._world.game.stage,
                        )
                    else:
                        quote_sale(robot.game.model_dump(mode='python'), request.parameters)
                except MarketRuleError as error:
                    raise WorldStateError(error.code, error.message) from error
            if request.action == 'PLANT':
                try:
                    quote_planting(
                        robot.game.model_dump(mode='python'),
                        self._world.farm.model_dump(mode='python'),
                        request.parameters,
                        current_stage=self._world.game.stage,
                    )
                except CropRuleError as error:
                    raise WorldStateError(error.code, error.message) from error
            if request.action == 'HARVEST':
                try:
                    quote_harvest(
                        self._world.farm.model_dump(mode='python'),
                        request.parameters,
                    )
                except CropRuleError as error:
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
                    'Return to homebase.'
                    if request.action == 'RETURN_HOME'
                    else (
                        f'Travel to {request.location}.'
                        if request.action == 'MOVE_TO'
                        else (
                            f'Begin {activity.label} at {request.location}.'
                            if activity is not None
                            else (
                                'Plant a crop at the farm.'
                                if request.action == 'PLANT'
                                else f'{request.action.title()} an item at market.'
                            )
                        )
                    )
                ),
                error=None,
            )
            world = self._world.model_dump(mode='python')
            robot_data = next(item for item in world['robots'] if item['id'] == robot.id)
            robot_data['task'] = task.model_dump(mode='python')
            world['revision'] = next_revision
            world['updated_at'] = now
            if agent_decision:
                world['events'].append({
                    'id': f'event-{task.id}-agent-decision',
                    'timestamp': now,
                    'type': 'agent_decision',
                    'robot_id': robot.id,
                    'task_id': task.id,
                    'message': f'{robot.name} decided to {request.action.lower()}: {task.reason}',
                    'data': {
                        'action': request.action,
                        'location': request.location,
                        'parameters': request.parameters,
                        'reason': task.reason,
                    },
                })
            world['events'].append({
                'id': f'event-{task.id}-assigned',
                'timestamp': now,
                'type': 'task_assigned',
                'robot_id': robot.id,
                'task_id': task.id,
                'message': (
                    f'{robot.name} was assigned to return home.'
                    if request.action == 'RETURN_HOME'
                    else (
                        f'{robot.name} was assigned to travel to {request.location}.'
                        if request.action == 'MOVE_TO'
                        else (
                            f'{robot.name} was assigned to {activity.label} at {request.location}.'
                            if activity is not None
                            else (
                                f'{robot.name} was assigned to plant at the farm.'
                                if request.action == 'PLANT'
                                else (
                                    f'{robot.name} was assigned to '
                                    f'{request.action.lower()} an item at market.'
                                )
                            )
                        )
                    )
                ),
                'data': {},
            })
            world['events'] = world['events'][-100:]
            self._publish(world)
            self._task_requests[request.request_id] = (
                request.model_copy(deep=True),
                task.model_copy(deep=True),
            )
            return task.model_copy(deep=True)

    def assign_task_for_session(
        self,
        session_id: str,
        request: TaskRequest,
    ) -> RobotTask:
        """Atomically reject stale autonomous work before normal task validation."""
        with self._lock:
            if session_id != self._world.session_id:
                raise WorldStateError(
                    'SESSION_MISMATCH',
                    'The task request belongs to a different game session.',
                )
            return self.assign_task(request, agent_decision=True)

    def assign_move_task(self, request: TaskRequest) -> RobotTask:
        """Compatibility alias for callers created before activity tasks existed."""
        return self.assign_task(request)

    def confirm_arrival(self, robot_id: str, report: ArrivalReport) -> bool:
        with self._lock:
            if report.session_id != self._world.session_id:
                raise WorldStateError(
                    'SESSION_MISMATCH',
                    'The arrival report belongs to a different game session.',
                )

            robot = next(
                (candidate for candidate in self._world.robots if candidate.id == robot_id),
                None,
            )
            if robot is None:
                raise WorldStateError('NOT_FOUND', f'Unknown robot {robot_id!r}.')

            arrival_key = (report.session_id, robot_id, report.task_id)
            accepted_location = self._accepted_arrivals.get(arrival_key)
            if accepted_location is not None:
                if accepted_location == report.location:
                    return True
                raise WorldStateError(
                    'TASK_MISMATCH',
                    'The arrival location does not match the previously accepted report.',
                )

            task = robot.task
            if (
                task is None
                or task.id != report.task_id
                or task.location != report.location
                or task.status not in ('ASSIGNED', 'NAVIGATING')
            ):
                raise WorldStateError(
                    'TASK_MISMATCH',
                    'The arrival report does not match the robot\'s active navigation task.',
                )

            now = datetime.now(timezone.utc)
            world = self._world.model_dump(mode='python')
            robot_data = next(item for item in world['robots'] if item['id'] == robot_id)
            self._apply_arrival(world, robot_data, robot_data['task'], report.location, now)
            world['revision'] += 1
            world['updated_at'] = now
            world['events'] = world['events'][-100:]
            self._publish(world)
            self._accepted_arrivals[arrival_key] = report.location
            return True

    def report_blocked(self, robot_id: str, report: BlockedReport) -> bool:
        with self._lock:
            if report.session_id != self._world.session_id:
                raise WorldStateError(
                    'SESSION_MISMATCH',
                    'The blocked report belongs to a different game session.',
                )

            robot = next(
                (candidate for candidate in self._world.robots if candidate.id == robot_id),
                None,
            )
            if robot is None:
                raise WorldStateError('NOT_FOUND', f'Unknown robot {robot_id!r}.')
            task = robot.task
            if (
                task is None
                or task.id != report.task_id
                or task.status not in ('ASSIGNED', 'NAVIGATING')
            ):
                raise WorldStateError(
                    'TASK_MISMATCH',
                    'The blocked report does not match the robot\'s active navigation task.',
                )
            if robot.physical.blocked:
                return True

            now = datetime.now(timezone.utc)
            world = self._world.model_dump(mode='python')
            robot_data = next(item for item in world['robots'] if item['id'] == robot_id)
            robot_data['physical']['blocked'] = True
            world['revision'] += 1
            world['updated_at'] = now
            world['events'].append({
                'id': f"event-blocked-{world['revision']}",
                'timestamp': now,
                'type': 'robot_blocked',
                'robot_id': robot_id,
                'task_id': task.id,
                'message': f"{robot.name} reported blocked movement: {report.reason}.",
                'data': {
                    'reason': report.reason,
                    'duration_ms': report.duration_ms,
                },
            })
            world['events'] = world['events'][-100:]
            self._publish(world)
            return True

    def apply_navigation_steps(self, steps: list[NavigationStep]) -> WorldSnapshot:
        with self._lock:
            if not steps:
                return self._world.model_copy(deep=True)

            now = datetime.now(timezone.utc)
            world = self._world.model_dump(mode='python')
            changed = False
            accepted_arrivals = []

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
                        task['action'] not in ('MOVE_TO', 'RETURN_HOME', 'BUY', 'SELL', 'PLANT')
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
                    self._apply_arrival(world, robot, task, step.location, now)
                    accepted_arrivals.append((robot['id'], task['id'], step.location))
                else:
                    robot['game']['location'] = None
                    task['status'] = 'NAVIGATING'

            if not changed:
                return self._world.model_copy(deep=True)

            world['revision'] += 1
            world['updated_at'] = now
            world['events'] = world['events'][-100:]
            self._publish(world)
            for robot_id, task_id, location in accepted_arrivals:
                arrival_key = (self._world.session_id, robot_id, task_id)
                self._accepted_arrivals[arrival_key] = location
            return self._world.model_copy(deep=True)

    def _apply_arrival(
        self,
        world: dict,
        robot: dict,
        task: dict,
        location: str,
        now: datetime,
    ) -> None:
        robot['game']['location'] = location
        world['events'].append({
            'id': f"event-{task['id']}-arrived",
            'timestamp': now,
            'type': 'robot_arrived',
            'robot_id': robot['id'],
            'task_id': task['id'],
            'message': f"{robot['name']} arrived at {location}.",
            'data': {},
        })
        activity = activity_for(task['action'])
        if task['action'] == 'BUY':
            self._complete_purchase(world, robot, task, now)
        elif task['action'] == 'SELL':
            self._complete_sale(world, robot, task, now)
        elif task['action'] == 'PLANT':
            self._complete_planting(world, robot, task, now)
        elif activity is None:
            robot['task'] = None
            world['events'].append({
                'id': f"event-{task['id']}-completed",
                'timestamp': now,
                'type': 'task_completed',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': (
                    f"{robot['name']} returned home."
                    if task['action'] == 'RETURN_HOME'
                    else f"{robot['name']} completed the move."
                ),
                'data': {},
            })
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

    def _complete_planting(
        self,
        world: dict,
        robot: dict,
        task: dict,
        now: datetime,
    ) -> None:
        try:
            quote = apply_planting(
                robot['game'],
                world['farm'],
                task['parameters'],
                current_stage=world['game']['stage'],
                planted_by=robot['id'],
                planted_at=now,
            )
        except CropRuleError as error:
            robot['task'] = None
            world['events'].append({
                'id': f"event-{task['id']}-failed",
                'timestamp': now,
                'type': 'task_failed',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} could not plant the crop: {error.message}",
                'data': {'code': error.code},
            })
            return

        plot = next(
            item for item in world['farm']['plots'] if item['id'] == quote.plot_id
        )
        remaining = robot['game']['inventory'].get(
            quote.seed_item_id,
            {},
        ).get('quantity', 0)
        robot['task'] = None
        world['events'].extend([
            {
                'id': f"event-{task['id']}-inventory",
                'timestamp': now,
                'type': 'inventory_updated',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} used 1 {quote.seed_name}.",
                'data': {
                    'item': quote.seed_item_id,
                    'quantity': -1,
                    'total_quantity': remaining,
                },
            },
            {
                'id': f"event-{task['id']}-planted",
                'timestamp': now,
                'type': 'crop_planted',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} planted {quote.crop_name} in {quote.plot_id}.",
                'data': {
                    'plot_id': quote.plot_id,
                    'crop_id': quote.crop_id,
                    'ready_at': plot['ready_at'],
                },
            },
            {
                'id': f"event-{task['id']}-completed",
                'timestamp': now,
                'type': 'task_completed',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} completed planting {quote.crop_name}.",
                'data': {},
            },
        ])

    def _complete_harvest(
        self,
        world: dict,
        robot: dict,
        task: dict,
        now: datetime,
    ) -> None:
        try:
            quote = apply_harvest(
                robot['game'],
                world['farm'],
                task['parameters'],
            )
        except CropRuleError as error:
            robot['task'] = None
            world['events'].append({
                'id': f"event-{task['id']}-failed",
                'timestamp': now,
                'type': 'task_failed',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} could not harvest the crop: {error.message}",
                'data': {'code': error.code},
            })
            return

        total_quantity = robot['game']['inventory'][quote.crop_id]['quantity']
        robot['task'] = None
        world['events'].extend([
            {
                'id': f"event-{task['id']}-inventory",
                'timestamp': now,
                'type': 'inventory_updated',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': (
                    f"{robot['name']} collected {quote.quantity} "
                    f'{quote.crop_name}.'
                ),
                'data': {
                    'item': quote.crop_id,
                    'quantity': quote.quantity,
                    'total_quantity': total_quantity,
                },
            },
            {
                'id': f"event-{task['id']}-harvested",
                'timestamp': now,
                'type': 'crop_harvested',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} harvested {quote.crop_name} from {quote.plot_id}.",
                'data': {
                    'plot_id': quote.plot_id,
                    'crop_id': quote.crop_id,
                    'quantity': quote.quantity,
                },
            },
            {
                'id': f"event-{task['id']}-completed",
                'timestamp': now,
                'type': 'task_completed',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f"{robot['name']} completed harvesting {quote.crop_name}.",
                'data': {},
            },
        ])

    def _complete_purchase(self, world: dict, robot: dict, task: dict, now: datetime) -> None:
        try:
            quote = apply_purchase(
                robot['game'],
                world['market'],
                task['parameters'],
                current_stage=world['game']['stage'],
            )
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

        self._unlock_stages(world, current_gold, task, robot, now)

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

    @staticmethod
    def _unlock_stages(
        world: dict,
        current_gold: int,
        task: dict,
        robot: dict,
        now: datetime,
    ) -> None:
        current_stage = world['game'].get('stage', 1)
        for stage, threshold, item_id, item_name in STAGE_UNLOCKS:
            if stage <= current_stage or current_gold < threshold:
                continue
            world['game']['stage'] = stage
            current_stage = stage
            world['events'].append({
                'id': f"event-{task['id']}-stage-{stage}",
                'timestamp': now,
                'type': 'stage_unlocked',
                'robot_id': robot['id'],
                'task_id': task['id'],
                'message': f'The team unlocked Stage {stage}: {item_name}.',
                'data': {
                    'stage': stage,
                    'item': item_id,
                    'threshold': threshold,
                },
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
                    or physical['tracking'] != 'TRACKED'
                    or physical['pose'] is None
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

                if task['action'] == 'HARVEST':
                    self._complete_harvest(world, robot, task, now)
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
            self._publish(world)
            return self._world.model_copy(deep=True)

    def advance_crop_growth(
        self,
        now: datetime | None = None,
    ) -> WorldSnapshot:
        observed_at = datetime.now(timezone.utc) if now is None else now
        if observed_at.utcoffset() is None:
            raise ValueError('now must include timezone information')

        with self._lock:
            if self._world.game.status != 'RUNNING':
                return self._world.model_copy(deep=True)

            world = self._world.model_dump(mode='python')
            growing_plots = [
                plot
                for plot in world['farm']['plots']
                if plot['status'] == 'GROWING' and plot['ready_at'] <= observed_at
            ]
            if not growing_plots:
                return self._world.model_copy(deep=True)

            crop_names = {
                crop['id']: crop['name']
                for crop in world['farm']['crops']
            }
            next_revision = world['revision'] + 1
            for plot in growing_plots:
                plot['status'] = 'READY'
                crop_name = crop_names.get(plot['crop_id'], plot['crop_id'])
                world['events'].append({
                    'id': f"event-{plot['id']}-ready-{next_revision}",
                    'timestamp': observed_at,
                    'type': 'crop_ready',
                    'robot_id': plot['planted_by'],
                    'task_id': None,
                    'message': f"{crop_name} in {plot['id']} is ready to harvest.",
                    'data': {
                        'plot_id': plot['id'],
                        'crop_id': plot['crop_id'],
                        'ready_at': plot['ready_at'],
                    },
                })

            world['revision'] = next_revision
            world['updated_at'] = observed_at
            world['events'] = world['events'][-100:]
            self._publish(world)
            return self._world.model_copy(deep=True)
