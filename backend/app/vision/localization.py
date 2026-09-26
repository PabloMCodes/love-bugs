"""Frame-only ArUco tracking. No camera, GUI, or backend I/O."""

from dataclasses import asdict, dataclass
from math import atan2, degrees

import cv2
import numpy as np

from app.config import VisionConfig


@dataclass(frozen=True)
class RobotPose:
    robot_id: str
    marker_id: int
    center_x: float
    center_y: float
    x: float
    y: float
    heading: float
    zone: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ZoneChange:
    robot_id: str
    previous_zone: str | None
    zone: str | None
    type: str = 'zone_changed'

    def to_dict(self) -> dict:
        return asdict(self)


class ArucoTracker:
    def __init__(self, config: VisionConfig):
        self.config = config
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self.detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
        self._last_zones: dict[int, str | None] = {}

    def process(self, frame: np.ndarray, *, draw: bool = False):
        """Return (poses, changes); optionally annotate the supplied frame in place.

        Forward points toward the marker's canonical top edge. Missing markers
        produce no pose/event; their last observed zone survives occlusion.
        """
        height, width = frame.shape[:2]
        corners, ids, _ = self.detector.detectMarkers(frame)
        poses, changes = [], []
        if draw:
            for zone in self.config.zones:
                start = (int(zone.x_min * (width - 1)), int(zone.y_min * (height - 1)))
                end = (int(zone.x_max * (width - 1)), int(zone.y_max * (height - 1)))
                cv2.rectangle(frame, start, end, (180, 120, 0), 1)
                cv2.putText(frame, zone.name, start, cv2.FONT_HERSHEY_SIMPLEX, .5, (180, 120, 0), 1)
        if ids is None:
            return poses, changes
        if draw:
            cv2.aruco.drawDetectedMarkers(frame, corners, ids)
        for marker_corners, marker_id in zip(corners, ids.flatten()):
            marker_id = int(marker_id)
            points = marker_corners.reshape(4, 2)
            center = points.mean(axis=0)
            forward = (points[0] + points[1]) / 2 - center
            heading = degrees(atan2(float(forward[1]), float(forward[0]))) % 360
            x = float(np.clip(center[0] / max(width - 1, 1), 0, 1))
            y = float(np.clip(center[1] / max(height - 1, 1), 0, 1))
            zone = next((z.name for z in self.config.zones if z.contains(x, y)), None)
            robot_id = self.config.marker_to_robot.get(marker_id, f'aruco:{marker_id}')
            pose = RobotPose(robot_id, marker_id, float(center[0]), float(center[1]), x, y, heading, zone)
            poses.append(pose)
            previous = self._last_zones.get(marker_id)
            if previous != zone:
                changes.append(ZoneChange(robot_id, previous, zone))
            self._last_zones[marker_id] = zone
            if draw:
                origin = tuple(np.rint(center).astype(int))
                tip = tuple(np.rint(center + forward * 1.5).astype(int))
                cv2.circle(frame, origin, 4, (0, 0, 255), -1)
                cv2.arrowedLine(frame, origin, tip, (0, 0, 255), 2, tipLength=.3)
                label = f'ID {marker_id} x={x:.3f} y={y:.3f} h={heading:.1f}'
                cv2.putText(frame, label, (max(0, origin[0] - 100), max(20, origin[1] - 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 100, 0), 2)
        return poses, changes
