import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.config import VisionConfig, Zone, load_vision_config
from app.vision.capture import VideoSource
from app.vision.localization import ArucoTracker


def frame_with_markers(markers):
    frame = np.full((400, 600, 3), 255, dtype=np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for marker_id, x, y, rotations in markers:
        marker = cv2.aruco.generateImageMarker(dictionary, marker_id, 80)
        marker = np.rot90(marker, rotations)
        frame[y:y + 80, x:x + 80] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    return frame


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.tracker = ArucoTracker(VisionConfig({0: 'robot-a', 1: 'robot-b'}, (
            Zone('farm', 0, 0, .5, 1), Zone('lake', .7, 0, 1, 1))))

    def test_multiple_markers_and_heading(self):
        frame = frame_with_markers([(0, 40, 40, 0), (1, 440, 240, 1)])
        poses, events = self.tracker.process(frame, draw=True)
        by_id = {p.marker_id: p for p in poses}
        self.assertEqual(set(by_id), {0, 1})
        self.assertAlmostEqual(by_id[0].center_x, 79.5, delta=1)
        self.assertAlmostEqual(by_id[0].center_y, 79.5, delta=1)
        self.assertAlmostEqual(by_id[0].x, 79.5 / 599, places=3)
        self.assertAlmostEqual(by_id[0].y, 79.5 / 399, places=3)
        self.assertAlmostEqual(by_id[0].heading, 270, delta=1)
        self.assertAlmostEqual(by_id[1].heading, 180, delta=1)
        self.assertAlmostEqual(by_id[0].marker_radius, 80 / 2 ** .5, delta=2)
        self.assertEqual(by_id[0].to_dict()['robot_id'], 'robot-a')
        self.assertEqual(len(events), 2)

    def test_zone_transitions_and_occlusion(self):
        farm = frame_with_markers([(0, 40, 40, 0)])
        self.assertEqual(len(self.tracker.process(farm)[1]), 1)
        self.assertEqual(self.tracker.process(farm)[1], [])
        self.assertEqual(self.tracker.process(frame_with_markers([])), ([], []))
        self.assertEqual(self.tracker.process(farm)[1], [])
        events = self.tracker.process(frame_with_markers([(0, 300, 40, 0)]))[1]
        self.assertEqual((events[0].previous_zone, events[0].zone), ('farm', None))
        events = self.tracker.process(frame_with_markers([(0, 440, 40, 0)]))[1]
        self.assertEqual((events[0].previous_zone, events[0].zone), (None, 'lake'))
        events = self.tracker.process(farm)[1]
        self.assertEqual((events[0].previous_zone, events[0].zone), ('lake', 'farm'))

    def test_unknown_marker_and_configuration(self):
        poses, _ = self.tracker.process(frame_with_markers([(49, 40, 40, 0)]))
        self.assertEqual(poses[0].robot_id, 'aruco:49')
        config = load_vision_config(Path(__file__).resolve().parents[1] / 'vision_config.json')
        self.assertEqual(len(config.zones), 4)
        with self.assertRaises(ValueError):
            Zone('invalid', 0, 0, 2, 1)


class CaptureTests(unittest.TestCase):
    def test_video_eof(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'test.avi')
            writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'MJPG'), 10, (600, 400))
            self.assertTrue(writer.isOpened())
            for _ in range(3):
                writer.write(frame_with_markers([(0, 40, 40, 0)]))
            writer.release()
            with VideoSource(path) as source:
                for _ in range(3):
                    running, frame = source.read()
                    self.assertTrue(running)
                    self.assertEqual(len(ArucoTracker(VisionConfig({}, ())).process(frame)[0]), 1)
                self.assertEqual(source.read(), (False, None))
            self.assertFalse(source.capture.isOpened())
            result = subprocess.run(
                [sys.executable, '-m', 'app.vision', '--video', path, '--no-display'],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            records = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(len(records), 3)
            self.assertEqual(records[0]['poses'][0]['marker_id'], 0)
            self.assertIn('Video ended', result.stderr)

    @patch('app.vision.capture.cv2.VideoCapture')
    def test_live_retry_recovery_and_limit(self, factory):
        capture = factory.return_value
        capture.read.side_effect = [(False, None), (True, frame_with_markers([])),
                                    (False, None), (False, None)]
        with self.assertRaisesRegex(RuntimeError, 'consecutive reads'):
            with VideoSource(0, max_failed_frames=2) as source:
                self.assertEqual(source.read(), (True, None))
                self.assertIsNotNone(source.read()[1])
                self.assertEqual(source.failed_frames, 0)
                self.assertEqual(source.read(), (True, None))
                source.read()
        capture.release.assert_called_once()

    @patch('app.vision.capture.cv2.VideoCapture')
    def test_open_failure(self, factory):
        factory.return_value.isOpened.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'Cannot open video source'):
            with VideoSource('missing.mp4'):
                self.fail('Must not enter')
        factory.return_value.release.assert_called_once()


if __name__ == '__main__':
    unittest.main()
