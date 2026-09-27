# Teammate integration checklist

The application API is ready for frontend, agent, database, localization, and
robotics teammates to integrate against. [api.md](api.md) is the complete MVP v1
contract; this file is the practical handoff checklist. Read
[GAME_PLAN.md](GAME_PLAN.md) first for the shared game objective, current gameplay
gaps, milestone order, and end-to-end acceptance scenario.

## Current team milestone

WALL-Y now has a separate [click-to-drive bring-up tool](backend/app/navigation/README.md)
using the supplied BLE protocol and existing ArUco tracker. It deliberately does
not consume backend tasks or publish poses yet. Do not run it alongside another
motor controller. The original firmware is archived in `firmware/wall_y/wall_y.ino`.
The tool also supports two independent robots via `--robots-config
navigation_robots.json`, with per-robot calibration/targets and a shared emergency
stop. This local mode is still separate from backend autonomy and task execution.

The immediate milestone is Phase 1 of the game plan: a complete autonomous
simulation round in which Wall-y and Eeva start at home, collect different
resources, sell their own inventory, advance the shared repair fund, and trigger
one clear victory state. Teammate integrations should preserve that scenario in
hardware mode instead of introducing a second game loop.

## Shared setup

- Pull `main` and keep local secrets in ignored environment files or exported
  shell variables. Never commit `.env`, API keys, database credentials, or robot
  addresses.
- Run `git status` before editing and `git pull --rebase` before and after focused
  work. Stop instead of discarding or guessing through an ambiguous teammate
  conflict; commit and push each verified handoff.
- Use `http://localhost:8000` for HTTP and `ws://localhost:8000/events` for live
  world snapshots unless the deployment owner supplies another base URL.
- Start in `GAME_MODE=simulation` when testing application behavior. Use
  `GAME_MODE=hardware` only when telemetry and stop handling are connected.
- Read `GET /world` before sending any report. Copy the current `session_id`, robot
  ID, task ID, and destination from that response; do not hardcode session or task
  IDs.
- Treat the backend as authoritative for tasks, game state, inventory, gold,
  prices, rewards, and completion. Integrations must not write the database or
  calculate authoritative game results directly.
- Ignore unknown response fields and tolerate unknown event `type` values. Display
  an unknown event's `message` rather than failing.

## Run and verify the baseline

Backend, from the repository root:

```sh
cd backend
.venv/bin/python -m pip install -r requirements-dev.txt
GAME_MODE=simulation .venv/bin/python -m uvicorn app.main:app \
    --host 127.0.0.1 --port 8000
```

Frontend, in another terminal:

```sh
cd frontend
nvm use
npm ci
npm run dev
```

Before handing off an integration, run:

```sh
cd backend
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests
PYTHONPATH=. .venv/bin/python tests/http_smoke.py

cd ../frontend
npm run build
```

The HTTP smoke test starts its own temporary server and SQLite database. The one
credential-dependent TimescaleDB test is expected to skip when
`TEST_DATABASE_URL` is not configured.

## Contract quick reference

| Consumer | Stable integration surface |
| --- | --- |
| Frontend | `GET /world`, WebSocket `/events`, game/robot controls, `POST /goal`, `POST /tasks`, and focused query routes |
| Localization | `POST /robots/{id}/pose` |
| Navigation | World snapshots containing active tasks, `POST /robots/{id}/arrived`, and `POST /robots/{id}/blocked` |
| Robot adapter | World snapshots containing stop state and `POST /robots/{id}/health` |
| Agents | `POST /tasks` using the same validation as manual actions; agent-chat routes are a spectator preview |
| Database/history | Backend-owned persistence plus `GET /events` and `GET /robots/{id}/history` |

FastAPI's interactive route documentation is available at `/docs` while the
backend is running. Payload meaning and lifecycle rules live in [api.md](api.md).

## Frontend checklist

- Replace local state with each newer full `world_snapshot` from WebSocket
  `/events`. Ignore an equal or lower revision in the same session.
- Clear session-specific task/event tracking when `session_id` changes.
- Send commands over HTTP; the world WebSocket is server-to-client only.
- Render the returned robot list and market data instead of assuming fixed names,
  counts, balances, stock, or prices.
- Show connection loss and reconnect with bounded backoff. Fetch `GET /world` at
  startup, but do not let an older REST response overwrite a newer socket state.
- Set `VITE_API_BASE_URL` when the backend is not at `http://localhost:8000`, and
  add the exact browser origin to backend `FRONTEND_ORIGINS`.

## Localization checklist

- Convert camera coordinates into the world coordinate system returned by
  `GET /world`: origin at top left, x rightward, y downward, and heading in
  clockwise degrees from `[0, 360)`.
- Send timezone-aware, monotonically increasing timestamps with pose reports.
  Duplicate or older observations are safely rejected with `accepted: false`.
- In hardware mode, publish faster than `POSE_TIMEOUT_SECONDS` (default 2 seconds)
  or tracking becomes `STALE` and navigation pauses.
- Calibrate marker IDs, arena bounds, zones, and arrival tolerance using the real
  camera view. Do not infer task completion or grant rewards from localization.

## Navigation and robot-adapter checklist

- Consume full world snapshots and look for a robot task in `ASSIGNED` or
  `NAVIGATING`. Resolve `task.location` through `world.map.locations`.
- Carry `session_id`, `robot_id`, and `task_id` through the entire motion command.
  Discard queued motion if any of them changes, the task disappears, or the robot
  or game becomes stopped.
- Never drive unless the robot is online, unblocked, not stopped, has a fresh
  `TRACKED` pose, and still owns the matching task.
- Report confirmed arrival once through `/robots/{id}/arrived`; retries with the
  same session, task, and location are safe. Report an obstruction through
  `/robots/{id}/blocked`.
- Publish health faster than `HEALTH_TIMEOUT_SECONDS` (default 5 seconds), including
  online state, battery when known, and blocked state.
- Stop motors locally on lost commands. The required ESP32 watchdog and the final
  backend-to-robot transport are hardware responsibilities; network stop requests
  are not a replacement for the onboard watchdog.

There is intentionally no public motor-control endpoint in MVP v1. A navigation
adapter may run in the backend process or consume `/events`, then use the robotics
team's chosen private transport to reach the ESP32.

## Agent checklist

- Submit only `MOVE_TO`, `RETURN_HOME`, `HARVEST`, `FISH`, `BUY`, or `SELL` through
  `POST /tasks`. `WAIT` means do not submit a task.
- Generate one stable `request_id` per intended task and reuse it only when retrying
  that identical request. A retry returns the same task in its latest state.
- Respect the required locations and trade parameters documented in `api.md`.
- Treat an accepted task as assigned, not completed. Observe the task or world
  feed until it becomes `COMPLETED`, `FAILED`, or `CANCELLED`.
- Never generate motor values or bypass backend task and market validation.

## Persistence checklist

- SQLite at `SQLITE_PATH` is the local default. Set `DATABASE_URL` for PostgreSQL
  with TimescaleDB 2.13 or newer; the backend initializes its own tables.
- Start only after the database is reachable. A required persistence failure
  prevents startup or returns `503` without publishing an unrecorded state.
- Query supported history endpoints instead of changing tables directly. Older
  sessions remain historical; the backend starts a fresh live session after a
  process restart.

## Hardware handoff exit criteria

- `GET /world` reports `mode: "hardware"`.
- Every robot maintains fresh health and pose reports without watchdog expiry.
- Assigned tasks cause motion only while all safety predicates remain true.
- Arrival begins or completes the matching task exactly once.
- Blocked, offline, stale tracking, robot stop, game stop, and reset all halt
  physical motion.
- The ESP32 independently stops its motors when valid commands expire.
- The frontend reconnects and reconstructs the current state from one snapshot.

## Outside the frozen application contract

The ESP32 protocol, robot addresses, motor pins, command frequency, camera choice,
calibration values, physical arrival tolerance, deployment/authentication, and
optional cooperation mechanics remain team decisions. Coordinate any addition,
but do not change existing MVP v1 fields or meanings silently.

## Optional physical traffic adapter

`python -m app.navigation --phase 4 --robots-config navigation_robots.json
--traffic-config traffic_config.json --backend-url http://localhost:8000` consumes
`GET /world` in hardware mode and uses existing pose, health and arrival reports.
The health `blocked` flag reports local traffic faults. Camera calibration maps
pixel arena bounds linearly onto map width/height; see the navigation README.
Fleet mode always loads `backend/traffic_config.json` unless `--traffic-config`
selects another file; it never falls back to unguarded driving. The setup editor
uses the same default. Single-robot CLI phase 4 is rejected.
This adapter owns hardware telemetry: do not run another pose/health writer or
BLE controller for these robots simultaneously.

Additive endpoint: `POST /agent-chat/traffic` accepts
`{session_id, event_id, winner, yielder, detour}`. Participants must be distinct
`robot-a`/`robot-b`; the session must match the hardware world. Repeated event IDs
are idempotent within a session (bounded at 10,000; then 429). It publishes two
`kind: "traffic"`, `status: "traffic"` public messages on the existing chat feed;
these describe a local reservation, not a new game task or proof of arrival.
Existing world/task/WebSocket schemas are unchanged. Like the current demo APIs,
this endpoint assumes a trusted local network.
