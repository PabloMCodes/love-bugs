"""Deterministic robot movement for development without hardware."""

import asyncio
import math

from app.schemas import NavigationStep, Point, Pose
from app.state import WorldStore


def move_pose_toward(current: Pose, target: Point, step_distance: float) -> tuple[Pose, bool]:
    if not math.isfinite(step_distance) or step_distance <= 0:
        raise ValueError('step_distance must be a positive finite number')

    delta_x = target.x - current.x
    delta_y = target.y - current.y
    remaining = math.hypot(delta_x, delta_y)

    if remaining == 0:
        return current.model_copy(deep=True), True

    heading = math.degrees(math.atan2(delta_y, delta_x)) % 360
    if remaining <= step_distance:
        return Pose(x=target.x, y=target.y, heading=heading), True

    ratio = step_distance / remaining
    return Pose(
        x=current.x + delta_x * ratio,
        y=current.y + delta_y * ratio,
        heading=heading,
    ), False


class SimulationRunner:
    def __init__(self, store: WorldStore, *, interval_seconds: float = .25,
                 step_distance: float = 5):
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError('interval_seconds must be a positive finite number')
        if not math.isfinite(step_distance) or step_distance <= 0:
            raise ValueError('step_distance must be a positive finite number')
        self.store = store
        self.interval_seconds = interval_seconds
        self.step_distance = step_distance

    def tick(self) -> None:
        world = self.store.snapshot()
        if world.mode != 'simulation' or world.game.status != 'RUNNING':
            return

        self.store.advance_activities(self.interval_seconds)
        world = self.store.snapshot()
        steps = []
        for robot in world.robots:
            task = robot.task
            if (
                task is None
                or task.action not in ('MOVE_TO', 'HARVEST', 'FISH', 'SELL')
                or task.status not in ('ASSIGNED', 'NAVIGATING')
                or robot.physical.pose is None
                or not robot.physical.online
                or robot.physical.stopped
                or robot.physical.blocked
                or robot.physical.tracking != 'TRACKED'
            ):
                continue

            target = world.map.locations.get(task.location)
            if target is None:
                continue
            pose, arrived = move_pose_toward(
                robot.physical.pose,
                target,
                self.step_distance,
            )
            steps.append(NavigationStep(
                robot_id=robot.id,
                task_id=task.id,
                pose=pose,
                location=task.location,
                arrived=arrived,
            ))

        self.store.apply_navigation_steps(steps)

    async def run(self) -> None:
        try:
            while True:
                self.tick()
                await asyncio.sleep(self.interval_seconds)
        except asyncio.CancelledError:
            return
