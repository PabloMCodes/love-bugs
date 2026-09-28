"""Real HTTP bridge/game rules with synthetic camera frames and fake BLE writes."""
import asyncio
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

import httpx
import numpy as np

from app.agents.orchestrator import AgentOrchestrator
from app.agents.planner import MockPlanner
from app.agents.runtime import AutonomyRunner
from app.config import NavigationConfig, NavigationRobot
from app.main import create_app
from app.navigation.backend import BackendBridge, TaskFollower
from app.navigation.fleet import RobotControl
from app.navigation.traffic import TrafficController, full_camera_config
from app.simulation.simulator import SimulationRunner
from app.state import WorldStore, default_world


class HardwareGameplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_camera_paces_two_agent_tasks_and_resource_loop(self):
        geometry = full_camera_config()
        world = default_world('hardware')
        world['robots'][1]['game'].update(money=40, inventory={})
        world['game']['goal']['current'] = 80
        world['map']['locations'] = geometry.world_locations(100,100)
        for crop in world['farm']['crops']:
            crop['grow_seconds'] = .01
        store = WorldStore(world)
        app = create_app(world_store=store,run_simulator=False)
        transport = httpx.ASGITransport(app=app)
        api = httpx.AsyncClient(transport=transport,base_url='http://test')
        wire = httpx.AsyncClient(transport=transport,base_url='http://test')
        bridge = BackendBridge('http://test',geometry)
        follower = TaskFollower(bridge)
        traffic = TrafficController(geometry,disable_avoidance=True)
        robots = [RobotControl(NavigationRobot(rid,rid,NavigationConfig()),3)
                  for rid in ('robot-a','robot-b')]
        for robot in robots:
            robot.ble = SimpleNamespace(connected=True,last_command='S')
        positions = {r.profile.robot_id:list(geometry.service_points['homebase']) for r in robots}
        frame = np.zeros((720,1280,3),dtype=np.uint8)

        async def pump(seconds=.2,arm=False):
            deadline = time.monotonic()+seconds
            while time.monotonic() < deadline:
                now = time.monotonic()
                poses = {rid:SimpleNamespace(center_x=p[0],center_y=p[1],heading=0)
                         for rid,p in positions.items()}
                sample = (now,frame,poses)
                for robot in robots:
                    robot.observe(sample,now,4)
                current = bridge.current(now)
                follower.update(robots,sample,now,current,arm=arm)
                commands = traffic.update(robots,now,frame.shape[:2],4)
                for robot in robots:
                    # Simulate successful writes; actual movement is supplied only
                    # by the explicit camera positions below, never the simulator.
                    robot.ble.last_command = commands[robot.profile.robot_id]
                bridge.capture(robots,traffic)
                follower.report_arrivals(robots,current,traffic,now=now)
                await asyncio.sleep(.01)

        async def submit_and_arrive(action,location,parameters):
            response = await api.post('/tasks',json={'request_id':f'{action}-{store.snapshot().revision}',
                'robot_id':'robot-a','action':action,'location':location,'parameters':parameters})
            response.raise_for_status()
            await pump()
            self.assertEqual(robots[0].target,tuple(geometry.service_points[location]))
            positions['robot-a'] = list(geometry.service_points[location])
            await pump(.7)
            return response.json()

        with patch('app.navigation.backend.httpx.AsyncClient',return_value=wire):
            running = asyncio.create_task(bridge.run())
            try:
                await pump(.4)
                store.start_game()
                await pump(.2,arm=True)
                runner = AutonomyRunner(store,AgentOrchestrator(MockPlanner()))
                await runner.tick()
                await pump(.4)
                self.assertIsNone(bridge.error)
                self.assertTrue(all(r.task and r.task.action == 'BUY' for r in store.snapshot().robots))
                self.assertTrue(all(r.target == tuple(geometry.service_points['market']) for r in robots))
                initial_money = [r.game.money for r in store.snapshot().robots]
                simulator = SimulationRunner(store,interval_seconds=2.5,step_distance=100)
                for _ in range(20):
                    simulator.tick()
                self.assertEqual([r.game.money for r in store.snapshot().robots],initial_money)
                self.assertTrue(all(r.task is not None for r in store.snapshot().robots))
                # UI world follows an intermediate measured position, not a target teleport.
                positions['robot-a'] = [800,400]
                await pump(.25)
                snapshot = (await api.get('/world')).json()
                self.assertAlmostEqual(snapshot['robots'][0]['physical']['pose']['x'],62.5)
                self.assertEqual(snapshot['robots'][0]['game']['money'],initial_money[0])
                positions['robot-a'] = list(geometry.service_points['market'])
                positions['robot-b'] = list(geometry.waiting_points['market'])
                await pump(.15)
                self.assertEqual([r.game.money for r in store.snapshot().robots],initial_money)
                await pump(.65)
                self.assertIsNone(store.robot('robot-a').task)
                self.assertIsNotNone(store.robot('robot-b').task)
                # Apply the peer-clearance motion that the synthetic camera does
                # not derive from BLE commands before the yielder approaches.
                positions['robot-a'] = list(geometry.waiting_points['market'])
                positions['robot-b'] = list(geometry.service_points['market'])
                await pump(.65)
                self.assertTrue(all(r.task is None for r in store.snapshot().robots))
                self.assertTrue(all(r.game.money < initial_money[i] for i,r in enumerate(store.snapshot().robots)))
                seed = next(k for k in store.robot('robot-a').game.inventory if k.endswith('seeds'))
                plot = store.snapshot().farm.plots[0].id
                await submit_and_arrive('PLANT','farm',{'item':seed,'plot_id':plot})
                store.advance_crop_growth()
                self.assertEqual(store.snapshot().farm.plots[0].status,'READY')
                await submit_and_arrive('HARVEST','farm',{'plot_id':plot})
                self.assertEqual(store.robot('robot-a').task.status,'ACTIVE')
                store.advance_activities(60)
                crop = next(k for k,v in store.robot('robot-a').game.inventory.items()
                            if not k.endswith('seeds') and v.quantity > 0)
                quantity = store.robot('robot-a').game.inventory[crop].quantity
                before_sale = store.robot('robot-a').game.money
                # The synthetic harness does not apply peer-escape motor output;
                # represent the idle peer having cleared the shared market slot.
                positions['robot-b'] = list(geometry.service_points['homebase'])
                await submit_and_arrive('SELL','market',{'item':crop,'quantity':quantity})
                self.assertGreater(store.robot('robot-a').game.money,before_sale)
                task = await submit_and_arrive('FISH','lake',{})
                self.assertEqual(store.robot('robot-a').task.status,'ACTIVE')
                store.advance_activities(task['parameters']['duration_seconds'])
                fish = task['parameters']['catch']['item_id']
                self.assertEqual(store.robot('robot-a').game.inventory[fish].quantity,1)
                await submit_and_arrive('SELL','market',{'item':fish,'quantity':1})
                # Identical accepted arrival never repeats a sale.
                completed = store.tasks()[-1]
                money = store.robot('robot-a').game.money
                response = await api.post('/robots/robot-a/arrived',json={
                    'session_id':store.snapshot().session_id,'task_id':completed.id,'location':'market'})
                response.raise_for_status()
                self.assertEqual(store.robot('robot-a').game.money,money)
                self.assertIsNone(store.robot('robot-a').physical.battery)
                bridge.request_stop()
                follower.stop(robots)
                await pump(.3)
                self.assertEqual(store.snapshot().game.status,'STOPPED')
            finally:
                running.cancel()
                await asyncio.gather(running,return_exceptions=True)
                await api.aclose()

    def test_repeated_frame_does_not_look_like_new_telemetry(self):
        bridge = BackendBridge('http://test',full_camera_config())
        robot = RobotControl(NavigationRobot('robot-a','WALL-Y',NavigationConfig()),3)
        robot.ble = SimpleNamespace(connected=True)
        robot.pose = SimpleNamespace(center_x=100,center_y=100,heading=0)
        robot.last_seen = time.monotonic()
        traffic = SimpleNamespace(blocked=False,events=[])
        bridge.capture([robot],traffic)
        first = bridge.sample[0]['timestamp']
        bridge.capture([robot],traffic)
        self.assertEqual(bridge.sample[0]['timestamp'],first)
