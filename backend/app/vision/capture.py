"""Video file/camera input independent of marker tracking."""

import logging
import sys

import cv2

logger = logging.getLogger(__name__)


class VideoSource:
    def __init__(self, source: str | int, max_failed_frames: int = 30):
        self.source = source
        self.live = isinstance(source, int)
        self.max_failed_frames = max_failed_frames
        self.failed_frames = 0
        self.capture = None

    def __enter__(self):
        api = cv2.CAP_AVFOUNDATION if self.live and sys.platform == 'darwin' else cv2.CAP_ANY
        self.capture = cv2.VideoCapture(self.source, api)
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError(f'Cannot open video source {self.source!r}. Check the file path or '
                               'camera index and macOS camera permissions/Continuity Camera availability.')
        return self

    def read(self):
        """Return (continue_running, frame); frame=None means a transient failure."""
        ok, frame = self.capture.read()
        if ok and frame is not None and frame.size:
            self.failed_frames = 0
            return True, frame
        if not self.live:
            return False, None
        self.failed_frames += 1
        if self.failed_frames == 1:
            logger.warning('Camera frame unavailable; retrying')
        if self.failed_frames >= self.max_failed_frames:
            raise RuntimeError(f'Camera {self.source} failed for {self.failed_frames} consecutive reads')
        return True, None

    def __exit__(self, *args):
        self.capture.release()
