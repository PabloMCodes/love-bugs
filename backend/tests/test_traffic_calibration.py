import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

import cv2
import numpy as np

from app.navigation.calibrate import Editor, footprint_radius, rectangle
from app.navigation.traffic import TrafficConfig, TrafficController
from app.navigation.backend import BackendBridge
from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def destinations():
    return TrafficConfig(arena=[100,100,1180,620],
        service_points={'homebase':[250,250], 'farm':[500,250],
                        'lake':[750,250], 'market':[1000,250]},
        waiting_points={'homebase':[250,450], 'farm':[500,450],
                        'lake':[750,450], 'market':[1000,450]})


class CalibrationTests(unittest.TestCase):
    def test_full_camera_backend_uses_preset_without_saved_file(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(game_mode='hardware',hardware_layout='full-camera',
                hardware_traffic_config='/missing/config.json',database_url=None,
                sqlite_path=str(Path(directory)/'preset.sqlite3'))
            with TestClient(create_app(settings=settings,run_simulator=False)) as client:
                world = client.get('/world').json()
                self.assertEqual(world['map']['locations']['homebase'],{'x':50.,'y':85.})
                self.assertEqual(world['map']['locations']['market'],{'x':85.,'y':15.})

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

    def test_click_named_points_save_reload_and_resolution_invalidation(self):
        editor = Editor(destinations(),1280,720)
        editor.select('service:farm')
        editor.mouse(cv2.EVENT_LBUTTONDOWN,550,250,0,None)
        editor.mouse(cv2.EVENT_LBUTTONUP,550,250,0,None)
        editor.select('waiting:farm')
        editor.mouse(cv2.EVENT_LBUTTONDOWN,550,450,0,None)
        self.assertEqual(editor.config.service_points['farm'],[550,250])
        self.assertEqual(editor.config.waiting_points['farm'],[550,450])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'points.json'
            editor.save(path,None)
            loaded = TrafficConfig.load(path)
            loaded.validate_destinations()
            self.assertEqual(loaded.service_points,editor.config.service_points)
            self.assertFalse(loaded.calibrated)
        resized = Editor(editor.config,640,480)
        self.assertEqual(resized.config.service_points,{})
        self.assertEqual(resized.config.waiting_points,{})

    def test_invalid_click_preserves_previous_destination(self):
        editor = Editor(destinations(),1280,720)
        editor.select('service:farm')
        editor.mouse(cv2.EVENT_LBUTTONDOWN,101,101,0,None)
        self.assertIn('clearance',editor.message)
        self.assertEqual(editor.config.service_points['farm'],[500,250])

    def test_clearance_missing_points_and_wait_separation(self):
        geometry = destinations()
        for point in ([101,101], [float('nan'),250], [True,250], [500]):
            with self.assertRaises(ValueError):
                replace(geometry,service_points={'farm':point})
        with self.assertRaisesRegex(ValueError,'buildings'):
            replace(geometry,obstacles=[[480,230,520,270]])
        with self.assertRaisesRegex(ValueError,'Configure service'):
            TrafficConfig().validate_destinations()
        geometry.waiting_points['farm'] = [510,250]
        with self.assertRaisesRegex(ValueError,'too close'):
            geometry.validate_destinations()

    def test_world_conversion_roundtrip_and_map_mismatch(self):
        geometry = destinations()
        world = {'map': {'width':100,'height':100,
                         'locations':geometry.world_locations(100,100)}}
        bridge = BackendBridge('http://test',geometry)
        bridge.validate_map(world)
        for name, point in geometry.service_points.items():
            x,y = bridge.target(name,world)
            self.assertAlmostEqual(x,point[0])
            self.assertAlmostEqual(y,point[1])
        world['map']['locations']['farm']['x'] += 1
        with self.assertRaisesRegex(ValueError,'map mismatch'):
            bridge.validate_map(world)

    def test_hardware_backend_loads_map_and_preserves_it_on_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'traffic.json'
            geometry = destinations()
            path.write_text(json.dumps(asdict(geometry)))
            settings = Settings(game_mode='hardware',hardware_traffic_config=str(path),
                                database_url=None,sqlite_path=str(Path(directory)/'test.sqlite3'))
            with TestClient(create_app(settings=settings,run_simulator=False)) as client:
                world = client.get('/world').json()
                self.assertEqual(world['map']['locations'],geometry.world_locations(100,100))
                self.assertIsNone(world['robots'][0]['physical']['pose'])
                reset = client.post('/game/reset')
                reset.raise_for_status()
                self.assertEqual(reset.json()['map'],world['map'])
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError,'Configure service'):
                create_app(settings=settings,run_simulator=False)
