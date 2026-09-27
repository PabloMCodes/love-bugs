import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.config import Settings
from app.persistence.__main__ import main
from app.persistence.store import DatabaseSetupError, Store, require_timescale


class DatabaseSetupTests(unittest.TestCase):
    def test_nested_sqlite_path_init_check_and_reinitialize_preserve_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'data'/'demo.sqlite3'
            store = Store(Settings(database_url=None, sqlite_path=str(path)))
            with self.assertRaises(Exception):
                store.check()
            self.assertFalse(path.exists())  # Checking must not create an empty database.
            store.initialize()
            with store.connection() as conn:
                conn.execute('INSERT INTO world_state VALUES (?, ?)', ('retained','{}'))
            store.initialize()
            result = store.check()
            self.assertTrue(result['ready'])
            self.assertEqual(result['backend'], 'sqlite')
            self.assertEqual(len(result['tables']), 5)
            with store.connection() as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM world_state').fetchone()[0], 1)
            with self.assertRaises(KeyError):
                store.world('missing')

    def test_memory_sqlite_is_rejected_instead_of_losing_schema(self):
        for path in ('', ':memory:', 'file:memory?mode=memory'):
            with self.assertRaises(DatabaseSetupError):
                Store(Settings(database_url=None, sqlite_path=path)).initialize()

    def test_timescale_documented_minimum(self):
        conn = Mock()
        for version in (None, '2.12.2', '1.9.0', 'unknown'):
            conn.execute.return_value.fetchone.return_value = (version,) if version else None
            with self.assertRaises(DatabaseSetupError):
                require_timescale(conn)
        for version in ('2.13.0', '2.19.3', '3.0.0'):
            conn.execute.return_value.fetchone.return_value = (version,)
            self.assertEqual(require_timescale(conn), version)

    def test_cli_env_file_and_shell_precedence(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            config = Path(directory)/'.env'
            expected = Path(directory)/'chosen'/'world.sqlite3'
            config.write_text(f'SQLITE_PATH={expected}\n')
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['init','--env-file',str(config)]),0)
            self.assertTrue(json.loads(output.getvalue())['ready'])
            self.assertTrue(expected.exists())
            alternative = Path(directory)/'shell.sqlite3'
            os.environ['SQLITE_PATH'] = str(alternative)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['init','--env-file',str(config)]),0)
            self.assertTrue(alternative.exists())

    def test_cli_redacts_driver_failures_and_no_postgres_fallback(self):
        with patch.dict(os.environ, {'DATABASE_URL':'postgresql://private-secret'}, clear=True), \
                patch('app.persistence.store.Store.connection', side_effect=RuntimeError('private-secret')) as connect, \
                patch('sqlite3.connect') as sqlite, contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(['check']),1)
            self.assertNotIn('private-secret',error.getvalue())
            connect.assert_called_once()
            sqlite.assert_not_called()

    def test_incomplete_schema_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Settings(database_url=None,sqlite_path=str(Path(directory)/'db.sqlite3')))
            with store.connection() as conn:
                conn.execute('CREATE TABLE world_state (session_id TEXT)')
            with self.assertRaisesRegex(DatabaseSetupError, 'world_state.*init'):
                store.check()
