import unittest
from dataclasses import replace
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.config import NavigationConfig, NavigationRobot
from app.navigation.fleet import RobotControl
from app.navigation.controller import steer
from app.navigation.traffic import TrafficConfig, TrafficController, segment_distance
from app.navigation.backend import BackendBridge
from app.state import WorldStore, default_world
from app.main import create_app


def robot(robot_id, x, y, target):
    r = RobotControl(NavigationRobot(robot_id, robot_id, NavigationConfig()), 3)
    r.pose = SimpleNamespace(center_x=x, center_y=y, heading=0)
    r.target, r.target_valid, r.last_seen = target, target is not None, 10
    r.geometry = steer(r.pose, target, r.config) if target else None
    r.ble = SimpleNamespace(connected=True)
    r.gate.arm(10, True)
    return r


def config():
    return TrafficConfig(calibrated=True, frame_width=1000, frame_height=800,
                         arena=[0,0,1000,800], radii={'robot-a':30,'robot-b':30},
                         margin=20, max_speed=30, stop_latency=1)


class TrafficTests(unittest.TestCase):
    def test_segment_distance(self):
        self.assertEqual(segment_distance((5,5),(0,0),(10,0)),5)
        self.assertEqual(segment_distance((0,3),(0,0),(0,0)),3)

    def test_detour_segments_clear_circle_and_wall(self):
        c = config()
        c.obstacles = [[480,100,520,300]]
        t = TrafficController(c)
        peer = ((500,400),'robot-b')
        route = t.plan((150,400),(850,400),'robot-a',peer)
        self.assertGreater(len(route),1)
        points = [(150,400),*route]
        self.assertTrue(all(t.clear_segment(a,b,'robot-a',peer) for a,b in zip(points,points[1:])))
        self.assertEqual(route[-1],(850,400))
        self.assertEqual(t.plan((150,400),(500,400),'robot-a',peer),[])

    def test_handoff_wait_and_only_one_moves(self):
        t = TrafficController(config())
        robots = [robot('robot-a',150,200,(700,200)),robot('robot-b',150,600,(700,600))]
        self.assertEqual(set(t.update(robots,10,(800,1000),3).values()),{'S'})
        self.assertEqual(t.update(robots,11.1,(800,1000),3),{'robot-a':'F','robot-b':'S'})
        self.assertEqual(len(t.events),1)
        robots[0].target_valid=False
        self.assertEqual(set(t.update(robots,12,(800,1000),3).values()),{'S'})
        self.assertEqual(t.owner,'robot-b')
        self.assertEqual(t.update(robots,13.1,(800,1000),3)['robot-b'],'F')

    def test_missing_pose_and_close_distance_disarm_both(self):
        for missing in (True,False):
            t=TrafficController(config())
            robots=[robot('robot-a',150,200,(700,200)),robot('robot-b',200,200,None)]
            if missing:
                robots[1].pose=None
            self.assertEqual(set(t.update(robots,10,(800,1000),4).values()),{'S'})
            self.assertFalse(any(r.gate.armed for r in robots))

    def test_actual_heading_stopping_envelope(self):
        c=config()
        c.max_speed=900
        t=TrafficController(c)
        robots=[robot('robot-a',150,200,(700,200)),robot('robot-b',500,600,None)]
        self.assertEqual(t.update(robots,10,(800,1000),3)['robot-a'],'S')
        self.assertIn('stopping clearance',t.reason)

    def test_calibration_and_bounds_fail_closed(self):
        for c, shape in ((replace(config(),calibrated=False),(800,1000)),(config(),(720,1280))):
            t=TrafficController(c)
            robots=[robot('robot-a',150,200,(700,200)),robot('robot-b',150,600,None)]
            self.assertEqual(set(t.update(robots,10,shape,4).values()),{'S'})
            self.assertFalse(any(r.gate.armed for r in robots))
        with self.assertRaises(ValueError):
            replace(config(),max_speed=float('nan'))

    def test_bridge_geometry_and_staleness(self):
        b=BackendBridge('http://localhost',config())
        b.world={'map':{'width':10,'height':8,'locations':{'farm':{'x':5,'y':4}}}}
        b.updated=10
        self.assertEqual(b.target('farm',b.world),(500,400))
        self.assertIsNotNone(b.current(10.1))
        self.assertIsNone(b.current(11))

    def test_traffic_chat_idempotent_and_session_checked(self):
        store=WorldStore(default_world('hardware'))
        app=create_app(world_store=store,run_simulator=False)
        with TestClient(app) as client:
            session=client.get('/world').json()['session_id']
            data={'session_id':session,'event_id':'test','winner':'robot-a','yielder':'robot-b','detour':True}
            self.assertEqual(client.post('/agent-chat/traffic',json=data).status_code,200)
            self.assertEqual(client.post('/agent-chat/traffic',json=data).status_code,200)
            chat=client.get('/agent-chat').json()['messages']
            self.assertEqual(len(chat),2)
            self.assertTrue(all(m['kind']=='traffic' for m in chat))
            self.assertEqual(client.post('/agent-chat/traffic',json={**data,'session_id':'old'}).status_code,409)
            self.assertEqual(client.post('/agent-chat/traffic',json={**data,'yielder':'robot-a'}).status_code,422)


class TaskFollowerTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from app.navigation.backend import TaskFollower
        self.bridge=BackendBridge('http://localhost',config())
        self.follower=TaskFollower(self.bridge)
        self.robots=[robot('robot-a',150,200,None),robot('robot-b',150,600,None)]
        self.sample=(10,np.zeros((800,1000,3)),{r.profile.robot_id:r.pose for r in self.robots})
        self.world=default_world('hardware')
        self.world['game']['status']='RUNNING'
        for r in self.world['robots']:
            r['physical'].update(online=True,tracking='TRACKED',blocked=False,stopped=False)
        self.world['robots'][0]['task']={'id':'one','status':'NAVIGATING','location':'farm'}

    def test_requires_arm_then_new_tasks_follow_without_implicit_resume_after_loss(self):
        self.follower.update(self.robots,self.sample,10,self.world)
        self.assertFalse(self.robots[0].gate.armed)
        self.follower.update(self.robots,self.sample,10,self.world,arm=True)
        self.assertTrue(self.robots[0].gate.armed)
        self.world['robots'][0]['task']['id']='two'
        self.follower.update(self.robots,self.sample,10,self.world)
        self.assertTrue(self.robots[0].gate.armed)
        self.follower.update(self.robots,self.sample,10,None)
        self.follower.update(self.robots,self.sample,10,self.world)
        self.assertFalse(self.robots[0].gate.armed)
        self.assertIsNone(self.follower.session)

    def test_remote_stop_reset_blocked_and_cancel(self):
        from copy import deepcopy
        for change in ('stop','reset','blocked','cancel'):
            world=deepcopy(self.world)
            self.follower.update(self.robots,self.sample,10,world,arm=True)
            if change=='stop':
                world['game']['status']='STOPPED'
            elif change=='reset':
                world['session_id']='new'
            elif change=='blocked':
                world['robots'][0]['physical']['blocked']=True
            else:
                world['robots'][0]['task']=None
            self.follower.update(self.robots,self.sample,10,world)
            self.assertFalse(self.robots[0].gate.armed,change)

    def test_arrival_only_current_session_once(self):
        self.follower.update(self.robots,self.sample,10,self.world,arm=True)
        self.robots[0].geometry=SimpleNamespace(distance=0)
        traffic=SimpleNamespace(blocked=False)
        self.follower.report_arrivals(self.robots,self.world,traffic)
        self.follower.report_arrivals(self.robots,self.world,traffic)
        self.assertEqual(len(self.bridge.arrivals),1)
        self.follower.stop(self.robots)
        self.follower.arrived.clear()
        self.follower.report_arrivals(self.robots,self.world,traffic)
        self.assertEqual(len(self.bridge.arrivals),1)


class BridgeTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_routes_receive_telemetry_and_traffic(self):
        import asyncio
        import time
        import httpx
        from unittest.mock import patch
        from datetime import datetime, timezone
        store=WorldStore(default_world('hardware'))
        app=create_app(world_store=store,run_simulator=False)
        geometry = config()
        geometry.service_points = {name: [p['x']*10, p['y']*8]
                                   for name, p in default_world()['map']['locations'].items()}
        geometry.waiting_points = {name: [p[0], p[1]+100]
                                   for name, p in geometry.service_points.items()}
        bridge=BackendBridge('http://test',geometry)
        bridge.sample=[{'robot_id':'robot-a','online':True,'blocked':False,
            'pose':{'x':.2,'y':.3,'heading':90},'captured':time.monotonic(),
            'timestamp':datetime.now(timezone.utc).isoformat()}]
        client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test')
        with patch('app.navigation.backend.httpx.AsyncClient',return_value=client):
            task=asyncio.create_task(bridge.run())
            try:
                for _ in range(100):
                    if bridge.world:
                        break
                    await asyncio.sleep(.01)
                bridge.events.append({'event_id':'bridge','winner':'robot-a','yielder':'robot-b','detour':False})
                for _ in range(100):
                    if not bridge.events:
                        break
                    await asyncio.sleep(.01)
                self.assertIsNone(bridge.error)
                self.assertFalse(bridge.events)
                pose=store.robot('robot-a').physical.pose
                self.assertEqual((pose.x,pose.y,pose.heading),(20,30,90))
            finally:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
