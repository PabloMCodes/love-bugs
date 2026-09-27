"""Initialize or check game persistence without starting robots, agents or a game."""
import argparse
import json
from pathlib import Path
import sys

from app.config import Settings
from app.persistence.store import DatabaseSetupError, Store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'check'))
    parser.add_argument('--env-file', type=Path, help='Explicit local dotenv file; existing shell variables take precedence')
    args = parser.parse_args(argv)
    try:
        if args.env_file:
            if not args.env_file.is_file():
                raise DatabaseSetupError('Environment file not found; provide a local file with DATABASE_URL or SQLITE_PATH.')
            from dotenv import load_dotenv
            load_dotenv(args.env_file, override=False, interpolate=False)
        store = Store(Settings())
        if args.command == 'init':
            store.initialize()
        print(json.dumps(store.check(), indent=2))
        return 0
    except DatabaseSetupError as error:
        print(f'Database setup: {error}', file=sys.stderr)
    except Exception:
        # Driver exceptions may include URLs, credentials and internal server data.
        print('Database setup failed. Check connectivity, credentials and permissions; '
              'for SQLite, run init first. Connection details are not printed.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
