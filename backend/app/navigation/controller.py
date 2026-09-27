"""Pure pixel-space steering; image headings increase clockwise from right."""

from dataclasses import dataclass
from math import atan2, degrees, hypot

from app.config import NavigationConfig


def normalize_angle(angle: float) -> float:
    return (angle + 180) % 360 - 180


@dataclass(frozen=True)
class Steering:
    distance: float
    heading: float
    desired_heading: float
    error: float
    command: str


def steer(pose, target: tuple[float, float], config: NavigationConfig) -> Steering:
    dx, dy = target[0] - pose.center_x, target[1] - pose.center_y
    distance = hypot(dx, dy)
    heading = (pose.heading + config.heading_offset_degrees) % 360
    desired = degrees(atan2(dy, dx)) % 360
    error = normalize_angle(desired - heading)
    command = 'S'
    if distance >= config.stop_distance:
        if error > config.angle_threshold:
            command = 'L' if config.invert_turns else 'R'
        elif error < -config.angle_threshold:
            command = 'R' if config.invert_turns else 'L'
        else:
            command = 'F'
    return Steering(distance, heading, desired, error, command)


class MotionGate:
    """Latched arming and short movement pulses; never resume after tracking loss."""

    def __init__(self, config: NavigationConfig):
        self.config = config
        self.armed = False
        self.started = 0.0

    def arm(self, now: float, fresh: bool):
        self.armed = fresh
        self.started = now

    def stop(self):
        self.armed = False

    def command(self, desired: str, now: float, last_seen: float | None,
                visible: bool, connected: bool) -> str:
        if not connected or last_seen is None or now - last_seen >= self.config.marker_timeout:
            self.stop()
        if not self.armed or not visible:
            return 'S'
        if desired == 'S':
            self.stop()  # Arrival stays stopped even if the pose jitters afterward.
            return 'S'
        cycle = self.config.pulse_seconds + self.config.pause_seconds
        return desired if (now - self.started) % cycle < self.config.pulse_seconds else 'S'
