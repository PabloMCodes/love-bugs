"""CLI regressions for the missing --traffic-config boundary bypass."""
import contextlib
import io
import unittest
from unittest.mock import AsyncMock, patch

from app.navigation.__main__ import main
from app.navigation.calibrate import DEFAULT_TRAFFIC_CONFIG as EDITOR_CONFIG
from app.navigation.traffic import DEFAULT_TRAFFIC_CONFIG


class NavigationCliTests(unittest.TestCase):
    def test_old_single_robot_phase_four_rejected_before_hardware(self):
        with patch('sys.argv', ['navigation', '--camera', '1', '--phase', '4']), \
                patch('app.navigation.__main__.run', new_callable=AsyncMock) as run, \
                contextlib.redirect_stderr(io.StringIO()) as error:
            with self.assertRaises(SystemExit) as result:
                main()
            self.assertEqual(result.exception.code, 2)
            self.assertIn('does not enforce saved boundaries', error.getvalue())
            run.assert_not_awaited()

    def test_user_command_enters_protected_fleet_without_extra_flag(self):
        with patch('sys.argv', ['navigation', '--camera', '1', '--phase', '4',
                                '--robots-config', 'navigation_robots.json']), \
                patch('app.navigation.__main__.load_navigation_robots', return_value=()) as load, \
                patch('app.navigation.fleet.run_fleet', new_callable=AsyncMock) as fleet:
            self.assertEqual(main(), 0)
            fleet.assert_awaited_once()
            self.assertEqual(fleet.call_args.args[0].phase, 4)
            self.assertIsNone(fleet.call_args.args[0].traffic_config)
            load.assert_called_once()

    def test_editor_and_navigation_share_an_absolute_default(self):
        self.assertEqual(EDITOR_CONFIG, DEFAULT_TRAFFIC_CONFIG)
        self.assertTrue(DEFAULT_TRAFFIC_CONFIG.is_absolute())
        self.assertEqual(DEFAULT_TRAFFIC_CONFIG.name, 'traffic_config.json')
