"""Record validated live-world transitions without owning game rules."""
from app.persistence.models import Event, PositionSample
from app.state import WorldStateError


class WorldRecorder:
    def __init__(self, store):
        self.store = store

    def record(self, current, previous, *, position_source=None):
        world = current.model_dump(mode='json')
        if previous is not None and previous.session_id != current.session_id:
            previous = None
        previous_events = {event.id for event in previous.events} if previous else set()
        previous_robots = {robot.id: robot for robot in previous.robots} if previous else {}
        events = [Event.model_validate(event) for event in world['events']
                  if event['id'] not in previous_events]
        positions = []
        for robot in current.robots:
            physical = robot.physical
            old = previous_robots.get(robot.id)
            if physical.pose is None or physical.pose_updated_at is None:
                continue
            if old and old.physical.pose_updated_at == physical.pose_updated_at:
                continue
            positions.append(PositionSample(
                session_id=current.session_id, robot_id=robot.id,
                timestamp=physical.pose_updated_at,
                source=position_source or current.mode, pose=physical.pose.model_dump(),
            ))
        try:
            self.store.commit(world, events, positions)
        except Exception:
            raise WorldStateError('PERSISTENCE_UNAVAILABLE',
                                  'History unavailable; world update was not applied.') from None
