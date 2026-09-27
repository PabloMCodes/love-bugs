import unittest
from dataclasses import replace
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.config import NavigationConfig, NavigationRobot
from app.navigation.fleet import RobotControl
from app.navigation.controller import steer
from app.navigation.traffic import TrafficConfig, TrafficController, segment_distance, full_camera_config
from app.navigation.backend import BackendBridge
from app.state import WorldStore, default_world
from app.main import create_app


def robot(robot_id, x, y, target):
    r = RobotControl(NavigationRobot(robot_id, robot_id, NavigationConfig()), 3)
    r.pose = SimpleNamespace(center_x=x, center_y=y, heading=0)
    r.target, r.target_valid, r.last_seen = target, target is not None, 10
    r.geometry = steer(r.pose, target, r.config) if target else None
    r.ble = SimpleNamespace(connected=True,last_command='S')
    r.gate.arm(10, True)
    return r


def config():
    return TrafficConfig(calibrated=True, frame_width=1000, frame_height=800,
                         arena=[0,0,1000,800], radii={'robot-a':30,'robot-b':30},
                         margin=20, max_speed=30, stop_latency=1)


class TrafficTests(unittest.TestCase):
    def test_avoidance_off_drives_directly_but_marker_loss_stops_both(self):
        c = replace(config(),calibrated=False,arena=[200,100,800,700],
                    obstacles=[[100,150,500,250]])
        robots = [robot('robot-a',100,200,(700,200)),robot('robot-b',120,200,(700,200))]
        for r in robots:
            r.desired = r.geometry.command
        t = TrafficController(c,disable_avoidance=True)
        self.assertEqual(t.update(robots,10,(800,1000),4),{'robot-a':'F','robot-b':'F'})
        self.assertFalse(t.blocked)
        robots[0].pose = None
        self.assertEqual(set(t.update(robots,10.1,(800,1000),4).values()),{'S'})
        self.assertFalse(any(r.gate.armed for r in robots))

    def test_full_camera_preset_scales_to_resolution_and_backend_map(self):
        for width,height in ((640,480),(1920,1080)):
            c = full_camera_config(width,height)
            self.assertEqual(c.arena,[0,0,width,height])
            self.assertEqual(c.service_points['homebase'],[.5*width,.85*height])
            self.assertEqual(c.world_locations(100,100)['farm'],{'x':15.,'y':15.})
            self.assertFalse(c.calibrated)  # A preset is never a measured calibration.

    def test_temporary_boundary_override_keeps_peer_building_and_frame_checks(self):
        c = replace(config(),arena=[200,100,800,700],obstacles=[[400,200,450,250]])
        normal = TrafficController(c)
        temporary = TrafficController(c,ignore_arena_boundary=True)
        peer = ((650,600),'robot-b')
        self.assertFalse(normal.clear_segment((850,400),(900,400),'robot-a',peer))
        self.assertTrue(temporary.clear_segment((850,400),(900,400),'robot-a',peer))
        self.assertFalse(temporary.clear_segment((850,400),(1000,400),'robot-a',peer))
        self.assertFalse(temporary.clear_segment((350,225),(500,225),'robot-a',peer))
        self.assertFalse(temporary.clear_segment((600,600),(700,600),'robot-a',peer))
        self.assertEqual(c.arena,[200,100,800,700])

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
        self.follower.report_arrivals(self.robots,self.world,traffic,now=10)
        self.assertEqual(len(self.bridge.arrivals),0)
        self.robots[0].last_seen=10.31
        self.follower.report_arrivals(self.robots,self.world,traffic,now=10.31)
        self.follower.report_arrivals(self.robots,self.world,traffic,now=10.32)
        self.assertEqual(len(self.bridge.arrivals),1)
        self.follower.stop(self.robots)
        self.follower.arrived.clear()
        self.follower.report_arrivals(self.robots,self.world,traffic)
        self.assertEqual(len(self.bridge.arrivals),0)

    def test_pending_operator_stop_prevents_rearm_and_discards_queued_arrivals(self):
        self.follower.update(self.robots,self.sample,10,self.world,arm=True)
        self.bridge.world = self.world
        self.bridge.arrivals.append({'task_id':'one'})
        self.bridge.request_stop()
        self.follower.update(self.robots,self.sample,10,self.world,arm=True)
        self.assertFalse(self.robots[0].gate.armed)
        self.assertIsNone(self.follower.session)
        self.assertIsNone(self.bridge.current(10))
        self.assertEqual(self.bridge.arrivals,[])

    def test_arrival_requires_stop_and_distinct_fresh_frames(self):
        self.follower.update(self.robots,self.sample,10,self.world,arm=True)
        r = self.robots[0]
        r.geometry = SimpleNamespace(distance=0)
        traffic = SimpleNamespace(blocked=False)
        r.ble.last_command = 'F'
        self.follower.report_arrivals(self.robots,self.world,traffic,now=10)
        r.ble.last_command = 'S'
        self.follower.report_arrivals(self.robots,self.world,traffic,now=10.1)
        self.follower.report_arrivals(self.robots,self.world,traffic,now=10.4)
        self.assertEqual(self.bridge.arrivals,[])
        r.last_seen = 10.41
        self.follower.report_arrivals(self.robots,self.world,traffic,now=11)
        self.assertEqual(self.bridge.arrivals,[])

    def test_queued_arrival_rechecks_latest_pose_and_task(self):
        from unittest.mock import patch
        arrival = {'robot_id':'robot-a','session_id':self.world['session_id'],
                   'task_id':'one','location':'farm','tolerance_pixels':35}
        sample = {'robot_id':'robot-a','online':True,'blocked':False,
                  'captured':10,'pose':{'x':.2,'y':.5}}
        self.bridge.sample = [sample]
        with patch('app.navigation.backend.time.monotonic',return_value=10.1):
            self.assertTrue(self.bridge.arrival_is_current(arrival,self.world))
            sample['pose']['x'] = .8
            self.assertFalse(self.bridge.arrival_is_current(arrival,self.world))
            sample['pose']['x'] = .2
            self.world['robots'][0]['task']['id'] = 'replacement'
            self.assertFalse(self.bridge.arrival_is_current(arrival,self.world))


class OperatorStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_loop_retries_stop_before_map_validation(self):
        import asyncio
        import httpx
        from unittest.mock import patch
        store = WorldStore(default_world('hardware'))
        store.start_game()
        bridge = BackendBridge('http://test',config())  # No named points yet.
        bridge.request_stop()  # Also no cached world/session yet.
        attempts = []

        def respond(request):
            if request.url.path == '/world':
                return httpx.Response(200,json=store.snapshot().model_dump(mode='json'))
            self.assertEqual(request.url.path,'/game/stop')
            attempts.append(request)
            if len(attempts) == 1:
                return httpx.Response(503,json={'error':{'code':'PERSISTENCE_UNAVAILABLE'}})
            return httpx.Response(200,json=store.stop_game().model_dump(mode='json'))

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond),base_url='http://test')
        with patch('app.navigation.backend.httpx.AsyncClient',return_value=client):
            task = asyncio.create_task(bridge.run())
            try:
                for _ in range(100):
                    if bridge.pending_stop is None:
                        break
                    await asyncio.sleep(.01)
                self.assertIsNone(bridge.pending_stop)
                self.assertEqual(len(attempts),2)
                self.assertEqual(store.snapshot().game.status,'STOPPED')
            finally:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)

    async def test_stop_retries_then_cancels_backend_activity_once(self):
        import httpx
        from unittest.mock import AsyncMock
        from app.schemas import TaskRequest, ArrivalReport
        store = WorldStore(default_world())
        store.start_game()
        task = store.assign_task(TaskRequest(request_id='fish-stop',robot_id='robot-a',
                                            action='FISH',location='lake',parameters={}))
        session = store.snapshot().session_id
        store.confirm_arrival('robot-a',ArrivalReport(session_id=session,task_id=task.id,location='lake'))
        self.assertEqual(store.robot('robot-a').task.status,'ACTIVE')
        bridge = BackendBridge('http://test',config())
        bridge.world = store.snapshot().model_dump(mode='json')
        bridge.request_stop()
        failed = AsyncMock()
        failed.post.side_effect = httpx.ConnectError('offline')
        with self.assertRaises(httpx.ConnectError):
            await bridge.deliver_stop(failed)
        self.assertIsNotNone(bridge.pending_stop)
        app = create_app(world_store=store,run_simulator=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            await bridge.deliver_stop(client)
            self.assertIsNone(bridge.pending_stop)
            self.assertEqual(store.snapshot().game.status,'STOPPED')
            self.assertIsNone(store.robot('robot-a').task)
            before = store.snapshot().model_dump(mode='json')
            # A retry of the acknowledged request is idempotent.
            response = await client.post('/game/stop',json={'session_id':session})
            self.assertEqual(response.status_code,200)
            store.advance_activities(60)
            self.assertEqual(store.snapshot().model_dump(mode='json'),before)

    async def test_old_session_stop_cannot_stop_new_game(self):
        import httpx
        store = WorldStore(default_world('hardware'))
        bridge = BackendBridge('http://test',config())
        bridge.world = store.snapshot().model_dump(mode='json')
        bridge.request_stop()
        store.reset_game()
        store.start_game()
        app = create_app(world_store=store,run_simulator=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            await bridge.deliver_stop(client)
            self.assertIsNone(bridge.pending_stop)
            self.assertEqual(store.snapshot().game.status,'RUNNING')
            self.assertIsNone(bridge.current(10))
            # Existing browser bodyless stop remains supported.
            response = await client.post('/game/stop')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['game']['status'],'STOPPED')
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
