import unittest

from app.schemas import Point, Pose, TaskRequest
from app.simulation.simulator import SimulationRunner, move_pose_toward
from app.state import WorldStore


class MovementTests(unittest.TestCase):
    def test_move_pose_toward_uses_fixed_steps_and_snaps_on_arrival(self):
        pose, arrived = move_pose_toward(
            Pose(x=0, y=0, heading=90),
            target=Point(x=3, y=4),
            step_distance=2,
        )
        self.assertFalse(arrived)
        self.assertAlmostEqual(pose.x, 1.2)
        self.assertAlmostEqual(pose.y, 1.6)
        self.assertAlmostEqual(pose.heading, 53.130102, places=5)

        pose, arrived = move_pose_toward(
            pose,
            target=Point(x=3, y=4),
            step_distance=10,
        )
        self.assertTrue(arrived)
        self.assertEqual((pose.x, pose.y), (3, 4))

    def test_invalid_step_distance_is_rejected(self):
        with self.assertRaises(ValueError):
            move_pose_toward(
                Pose(x=0, y=0, heading=0),
                target=Point(x=1, y=1),
                step_distance=0,
            )


class SimulationRunnerTests(unittest.TestCase):
    def test_move_task_navigates_and_completes(self):
        store = WorldStore()
        store.start_game()
        store.assign_move_task(TaskRequest(
            request_id='simulation-move-001',
            robot_id='robot-a',
            action='MOVE_TO',
            location='farm',
        ))
        simulator = SimulationRunner(store, step_distance=5)

        simulator.tick()
        moving = store.snapshot().robots[0]
        self.assertEqual(moving.task.status, 'NAVIGATING')
        self.assertIsNone(moving.game.location)
        self.assertNotEqual((moving.physical.pose.x, moving.physical.pose.y), (12, 30))

        for _ in range(10):
            simulator.tick()

        world = store.snapshot()
        billy = world.robots[0]
        self.assertIsNone(billy.task)
        self.assertEqual(billy.game.location, 'farm')
        self.assertEqual((billy.physical.pose.x, billy.physical.pose.y), (20, 50))
        self.assertEqual(world.events[-1].type, 'robot_arrived')

    def test_idle_tick_does_not_change_revision(self):
        store = WorldStore()
        revision = store.snapshot().revision

        SimulationRunner(store).tick()

        self.assertEqual(store.snapshot().revision, revision)


if __name__ == '__main__':
    unittest.main()
