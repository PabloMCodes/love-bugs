"""One deterministic startup fixture, not a navigation or task simulator yet."""
from datetime import datetime, timezone

from app.schemas import Event, Pose, PositionSample
from app.state import initial_world


def seed_session(store, reset=False):
    world = initial_world()
    now = datetime.now(timezone.utc)
    positions, events = [], []
    for robot in world["robots"]:
        pose = Pose(x=50, y=50, heading=0)
        robot["physical"].update(online=False, pose=pose.model_dump(),
                                 pose_updated_at=now.isoformat(), tracking="TRACKED")
        robot["game"]["location"] = "homebase"
        positions.append(PositionSample(session_id=world["session_id"], robot_id=robot["id"],
                                        timestamp=now, source="simulation", pose=pose))
        events.append(Event(timestamp=now, type="robot_arrived", robot_id=robot["id"],
                            message=f'Simulated {robot["name"]} is at Home, the meeting point.',
                            data={"location": "homebase", "source": "simulation", "initial": True}))
    if reset:
        events.append(Event(timestamp=now, type="simulation_reset",
                            message="Simulation reset: cancelled previous work and returned both robots Home.",
                            data={"reason": "Start a fresh shared order without retaining resources or rewards."}))
    world.update(revision=1, updated_at=now.isoformat())
    store.commit(world, events, positions)
    return world["session_id"]
