import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.navigation.calibrate import Editor, footprint_radius, rectangle
from app.navigation.traffic import TrafficConfig, TrafficController


class CalibrationTests(unittest.TestCase):
    def test_reverse_drag_clipping_and_small_boxes(self):
        self.assertEqual(rectangle((120,90),(-5,10),100,80),[0,10,100,80])
        with self.assertRaises(ValueError):
            rectangle((5,5),(6,7),100,80)

    def test_marker_offset_increases_turning_radius(self):
        # 10 pixels/inch, robot 6.2 x 5.2 inches.
        box=[0,0,62,52]
        self.assertEqual(footprint_radius(box,(31,26)),41)
        self.assertGreater(footprint_radius(box,(10,26)),41)
        with self.assertRaises(ValueError):
            footprint_radius(box,(80,26))

    def test_draw_building_and_measure_robot(self):
        editor=Editor(TrafficConfig(),1280,720)
        editor.mouse(cv2.EVENT_LBUTTONDOWN,500,200,0,None)
        editor.mouse(cv2.EVENT_LBUTTONUP,600,400,0,None)
        self.assertEqual(editor.config.obstacles,[[500,200,600,400]])
        controller=TrafficController(editor.config)
        self.assertFalse(controller.clear_segment((300,300),(800,300),'robot-a',((1000,600),'robot-b')))
        editor.select('robot-a')
        editor.mouse(cv2.EVENT_LBUTTONDOWN,100,100,0,None)
        editor.mouse(cv2.EVENT_LBUTTONUP,162,152,0,None)
        editor.mouse(cv2.EVENT_LBUTTONDOWN,131,126,0,None)
        self.assertEqual(editor.config.radii['robot-a'],41)
        self.assertIsNone(editor.body)
        image = np.zeros((720,1280,3),dtype=np.uint8)
        rendered = editor.draw(image)
        self.assertTrue(rendered.any())
        self.assertFalse(image.any())

    def test_save_roundtrip_preserves_control_values_disables_motion_and_checks_conflicts(self):
        editor=Editor(TrafficConfig(calibrated=True,max_speed=111),1280,720)
        editor.config.obstacles=[[200,200,300,300]]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'traffic.json'
            original=editor.save(path,None)
            loaded=TrafficConfig.load(path)
            self.assertFalse(loaded.calibrated)
            self.assertEqual(loaded.max_speed,111)
            self.assertEqual(loaded.obstacles,editor.config.obstacles)
            path.write_text('{"teammate": "edit"}')
            with self.assertRaisesRegex(ValueError,'changed on disk'):
                editor.save(path,original)
            self.assertEqual(json.loads(path.read_text()),{'teammate':'edit'})

    def test_new_resolution_clears_old_geometry_and_requires_review(self):
        editor=Editor(TrafficConfig(calibrated=True,obstacles=[[100,100,200,200]]),640,480)
        self.assertFalse(editor.config.calibrated)
        self.assertEqual(editor.config.arena,[0,0,640,480])
        self.assertEqual(editor.config.obstacles,[])
        self.assertIn('BOTH robots',editor.message)
