# Backend

The Python backend uses FastAPI and Pydantic for HTTP, WebSocket updates, and API models.
`GET /world`, live `/events` snapshots, goal configuration, game lifecycle
controls, simulated `MOVE_TO`, `RETURN_HOME`, `HARVEST`, `FISH`, `BUY`, and `SELL`
tasks, robot stop/resume, pose, arrival, health, and blocked-state ingestion,
spectator agent chat, and standalone overhead vision are implemented.
[Standalone WALL-Y click-to-drive](app/navigation/README.md) provides phased
camera/BLE bring-up. Connecting this local controller to backend tasks, pose
ingestion and lifecycle controls remains integration work.

- `app/main.py`: application composition and background-work lifecycle.
- `app/config.py`: runtime settings and hardware configuration.
- `app/schemas.py`: validated canonical world snapshot models.
- `app/state.py`: authoritative in-memory world state and immutable snapshots.
- `app/api/`: `GET /world`, spectator agent chat, and planned game APIs.
- `app/game/`: session controls, task lifecycle, and market transactions.
- `app/agents/`: high-level task decisions through the same validation as manual requests.
- `app/vision/`: overhead camera localization and coordinate calibration.
- `app/navigation/`: deterministic movement, arrival detection, and stop handling.
- `app/robots/`: ESP32 communication and robot health reporting.
- `app/simulation/`: simulated movement and telemetry for development without hardware.

## How the pieces connect

The API and agents submit work to game logic. Game logic owns state changes, timers, and rewards, and requests movement from navigation. Vision supplies poses; navigation sends motor commands through the robot client. Simulation substitutes movement and telemetry while keeping the same game logic and frontend contract.

Start with modules in one backend process; separate processes only when integration needs justify it. Keep hardware I/O out of API handlers and game rules. Implement synchronization around shared state and transactions when adding concurrent work.

[api.md](../api.md) is the stable MVP v1 application contract. Teammates should
start with the shared [game plan](../GAME_PLAN.md), then use the practical
[integration checklist](../INTEGRATION.md). Hardware
transport, calibration, and ESP32 firmware remain integration decisions; the
onboard motor watchdog belongs in that firmware.

## Runtime mode

Simulation is the default and keeps the current browser demo working:

```sh
cd backend
GAME_MODE=simulation .venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8000
```

When the robotics stack is ready, launch the same API in hardware mode:

```sh
cd backend
GAME_MODE=hardware .venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8000
```

`GAME_MODE` is read at process startup and must be `simulation` or `hardware`.
The selected value appears in `GET /world` as `mode`. Hardware mode does not run
generated movement: robots begin offline with unknown pose, battery, tracking,
and game location. Adapter teammates should read the current `session_id`, publish
health and pose reports, then consume assigned tasks from `/world` and report
arrival or blockage through the documented endpoints.

The backend game loop remains active in hardware mode because harvesting and
fishing durations are authoritative game rules. It advances an `ACTIVE` task only
after navigation reports a valid arrival; it never changes hardware poses or
invents arrivals. Invalid `GAME_MODE` values stop startup with a configuration
error instead of silently choosing a mode. `backend/.env.example` lists the setting,
but the server reads exported environment variables and does not load that file
automatically.

## Configure the game goal

Set the shared gold target before starting the game:

```sh
curl -X POST http://localhost:8000/goal \
    -H 'Content-Type: application/json' \
    -d '{"type":"earn_gold","target":500}'
```

The game must be `READY`, and the target must be greater than the robots' current
combined gold. The response includes the authoritative current amount. Repeating
the same configuration is safe and does not create another state revision.

## Read-only game queries

Teammates can inspect focused resources without downloading and filtering the
entire world snapshot:

```sh
curl http://localhost:8000/robots
curl http://localhost:8000/robots/robot-a
curl http://localhost:8000/market
curl http://localhost:8000/tasks
curl http://localhost:8000/tasks/task-3
```

`GET /robots` returns `{"robots":[...]}` and `GET /tasks` returns
`{"tasks":[...]}` in stable creation order. Individual unknown robot or task IDs
return `404`. The task catalog covers the current session and retains active,
completed, failed, and cancelled tasks after they leave the robot's active `task`
field. Failed tasks include their stable error code and message. Reset starts a
new session with an empty task catalog; older semantic events remain accessible
through the persisted history endpoints.

## Localization integration

Camera/localization teammates can publish normalized world coordinates without
accessing game internals. Read the current `session_id` from `GET /world`, then
send timezone-aware observations:

```sh
curl -X POST http://localhost:8000/robots/robot-a/pose \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "demo-session-001",
    "pose": {"x": 42.1, "y": 63.5, "heading": 91.2},
    "timestamp": "2026-09-26T18:00:00Z"
  }'
```

An accepted observation returns `{"accepted":true}` and appears in `/world` and
the next `/events` snapshot. An older or duplicate timestamp returns
`{"accepted":false}` without changing the world revision. Unknown robots return
`404`; old session IDs return `409`; coordinates outside the configured map return
`400`. Pose reports mark tracking as `TRACKED` but do not infer zone arrival or
change game inventory, tasks, or rewards.

## Navigation arrival integration

After navigation reaches the assigned destination, report it with the current
session, task, and location IDs:

```sh
curl -X POST http://localhost:8000/robots/robot-a/arrived \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "demo-session-001",
    "task_id": "task-3",
    "location": "farm"
  }'
```

Use `GET /world` to obtain the active session and task IDs rather than hardcoding
the example values. The report must match the robot's active `ASSIGNED` or
`NAVIGATING` task. Valid reports return `{"accepted":true}` and apply the same
arrival transition used by simulation. Repeating an accepted report is safe and
does not execute its task again. Old sessions, mismatched tasks, and mismatched
locations return `409`.

## Navigation blocked integration

When navigation cannot continue, report the obstruction against the active task:

```sh
curl -X POST http://localhost:8000/robots/robot-a/blocked \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "demo-session-001",
    "task_id": "task-3",
    "reason": "obstacle",
    "duration_ms": 4000
  }'
```

The task must still be `ASSIGNED` or `NAVIGATING`. An accepted report sets the
robot's `physical.blocked` flag, pauses task advancement, and emits a
`robot_blocked` event containing the reason and duration. Repeating a report while
the robot remains blocked is safe and has no additional side effects. A deliberate
health report with `blocked: false` clears the condition so navigation can resume.
Old sessions and mismatched tasks return `409`.

## Game and robot safety controls

The backend exposes these bodyless control requests:

```sh
curl -X POST http://localhost:8000/game/stop
curl -X POST http://localhost:8000/game/start
curl -X POST http://localhost:8000/game/reset
curl -X POST http://localhost:8000/robots/robot-a/stop
curl -X POST http://localhost:8000/robots/robot-a/resume
```

Stopping the game cancels active tasks, latches every robot's `stopped` flag, and
pauses autonomous work. Starting again clears the game-level stop, but a robot
stopped through its own endpoint remains stopped until explicitly resumed.
Robot resume requires a running game, an online robot, fresh tracking, a known
pose, and no blocked condition. Repeating start or stop calls is safe and does not
repeat events.

Reset first stops and archives the current session, then creates a new `READY`
session at revision `1`. Simulation robots are placed at home and remain stopped
until the game starts. Hardware robots keep their last telemetry and pose, but
tracking becomes `STALE` so fresh localization is required before navigation.
Previous sessions remain available through the history endpoints.

## Robot health integration

The ESP32 communication adapter can publish connectivity, battery, and blocked
state using the same current game session ID:

```sh
curl -X POST http://localhost:8000/robots/robot-a/health \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "demo-session-001",
    "online": true,
    "battery": 0.82,
    "blocked": false
  }'
```

Battery is a fraction from `0` to `1`, or `null` when unavailable. Valid reports
return `{"accepted":true}`. Repeated heartbeats with unchanged values refresh the
backend's internal last-seen time without increasing the world revision. Online
and blocked transitions appear in the world event feed. An offline or blocked
robot cannot receive or advance movement tasks, but health reports do not directly
cancel its current task; explicit blocked and stop handling are separate adapters.

## Telemetry freshness

Hardware mode runs a backend watchdog with these defaults:

```sh
HEALTH_TIMEOUT_SECONDS=5
POSE_TIMEOUT_SECONDS=2
TELEMETRY_CHECK_INTERVAL_SECONDS=0.25
```

All values must be positive finite seconds and are read when the server starts.
Health and localization adapters must report more frequently than their respective
timeouts. Missing health reports change `physical.online` to `false`; missing
newer pose reports change tracking from `TRACKED` to `STALE`. The last pose is
preserved for display, but stale/offline robots cannot receive or advance tasks.
The current task remains assigned so a recovery policy can resume or explicitly
stop it. Fresh health and pose reports restore availability. Expiration publishes
`robot_offline` and `tracking_stale` events and is persisted like other world
transitions. The watchdog is disabled in simulation mode.

## Standalone overhead vision

Vision is implemented independently of the game server. Requires Python 3.10+.
From the repository root:

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.vision --video /absolute/path/to/recording.mp4
# Switch to a live camera (try the index for your iPhone):
python -m app.vision --camera 0
```

Use `q` in the preview to quit, or Ctrl-C. Add `--no-display` for JSON-only
output. Files stop at EOF (or an unreadable frame). Live input retries temporary
failed reads, stopping with an error after 30 consecutive failures. macOS uses
AVFoundation: enable Continuity Camera on the iPhone, make it available to the Mac,
and grant camera permission to the terminal/application running Python. Camera
indices vary by Mac; select the index that shows the iPhone feed.

Edit `backend/vision_config.json` (or pass `--config /path/to/config.json`):

- `marker_to_robot` maps DICT_4X4_50 IDs 0–49 to unique robot names. Unmapped
  markers are still reported as `aruco:<id>`; reserve that prefix for fallback IDs.
- `zones` contains normalized rectangular bounds for homebase, farm, lake, market.
  The sample bounds are placeholders to tune to the actual camera view. Bounds
  are inclusive; the first configured matching zone wins if rectangles overlap.

Coordinates use the full image: origin top left, x right, y down. `center_x` and
`center_y` are pixels; `x` and `y` are normalized by width−1 and height−1.
Heading is clockwise in [0, 360): right=0, down=90, left=180, up=270. Mount each
marker with its canonical top edge facing the robot's forward direction. This is
2D image localization, with no perspective/lens calibration or metric 3D pose.
Use a fixed overhead view; changing crop, rotation, or camera position requires
retuning zones. A future API adapter must multiply normalized x/y by 100 to match
`api.md`; this module makes no backend calls.

Each frame writes one JSON line to stdout with `poses` and `events`; logs go to
stderr. Poses include robot ID, marker ID, pixel center, normalized x/y, heading,
and zone (`null` outside all zones). `zone_changed` events include `robot_id`,
`previous_zone`, and `zone`: initial detection inside a zone emits entry, movement
between zones emits one transition, and leaving emits a transition to `null`.
Stationary observations emit no repeated events. An invisible marker has no fresh
pose; its last observed zone is retained so occlusion does not invent an exit.
Boundary jitter can produce real alternating observations; no debounce is applied.

For reuse, `ArucoTracker.process(frame)` returns `(poses, events)` as dataclasses
with `to_dict()` methods. `draw=True` annotates the frame in place with zone bounds,
marker outlines, centers, forward arrows, and ID/coordinates/heading labels.
`VideoSource` owns camera/file lifecycle separately. Detection uses OpenCV's
[ArucoDetector](https://docs.opencv.org/4.11.0/d2/d1a/classcv_1_1aruco_1_1ArucoDetector.html).

Run synthetic detection, zone transition, video EOF, and capture failure tests:

```sh
python -m unittest discover -s tests -v
```

## Per-robot agent orchestration

Each robot gets an independent Google ADK `LlmAgent` and runner using Gemini.
The default model is `gemini-3.5-flash-lite`; set `AGENT_MODEL` to change it.
Agents choose one high-level task and a short public reason. They never control
motors, assign rewards, or change game state themselves.

Install the updated `requirements.txt`, then run one offline planning round:

```sh
python -m app.agents --provider mock
```

This explicit mock policy proposes harvesting for Wall-y and fishing for Eeva.
It accepts tasks into a temporary in-memory demo snapshot only; it does not run
movement, harvest timers, or the frontend simulation. Output is labeled `dry_run`.
No API key or network access is used in mock mode.

For real Gemini decisions, set `GOOGLE_API_KEY` in your shell to an AI Studio API
key, set `GOOGLE_GENAI_USE_VERTEXAI=FALSE`, and run:

```sh
python -m app.agents --provider gemini
```

That makes real model calls but still uses the demo task sink, with no hardware
or backend calls. `--world /path/to/world.json` accepts a world snapshot instead;
the file is never modified. The game must be `RUNNING`, below its gold goal, with
idle, online, unblocked, unstopped robots whose tracking is `TRACKED` and pose is
known. Otherwise planning is skipped. Missing credentials, invalid decisions,
and model failures do not silently switch to the mock policy.

`backend/.env.example` lists configuration; the CLI reads exported environment
variables, not `.env` automatically. Defaults: `AGENT_INTERVAL_SECONDS=10` between
attempts per robot, `AGENT_TIMEOUT_SECONDS=20` per model call or submission. Each decision uses
one bounded model call, the current structured world, and no camera frames or
conversation history. Temporary ADK sessions are deleted after each decision.

Responsibilities:

- `app/agents/planner.py`: structured decisions, availability/trade checks, mock policy.
- `app/agents/gemini.py`: independent ADK agents, bounded JSON model responses.
- `app/agents/orchestrator.py`: scheduling, latest-state revalidation, task submission.
- `app/agents/__main__.py`: standalone dry-run demonstration.

For backend integration, keep one `AgentOrchestrator` for the game process and call
`await orchestrator.tick(read_world, submit_task)` from the backend lifecycle.
`read_world()` returns the current authoritative snapshot. Async
`submit_task(session_id, request)` must atomically revalidate through the same
service used by manual tasks, handle request-ID idempotency, reject old sessions,
and return `True` only after the accepted task is visible in the snapshot.
The request follows `api.md`; the host should publish an `agent_decision` event
from accepted outcomes. WAIT is internal and never submitted as an API task.

The scheduler runs agents sequentially so each sees its teammate's newly accepted
tasks. Overlapping ticks are skipped; busy robots never trigger model calls.
Planning errors are isolated per robot and retried only after the cooldown.
An uncertain submission blocks further planning for that robot until the host
reconciles the request ID and calls `reconcile(session_id, robot_id)`, or a new
game session starts. Stop/reset during planning is checked before submission.
Trade checks here are preflight only; the task service must recheck funds, stock,
and inventory atomically at execution. The host owns freshness thresholds and
must mark stale camera poses as `STALE` before allowing physical tasks.

The frontend now reads the authoritative backend world, owns only session controls
and seed-purchase interactions, and keeps a local simulation fallback. Movement,
collection, and sales normally come from the backend orchestrator through the
shared task service. The frontend conversation panel is a read-only spectator feed.
Authoritative buy prices come from `world.market.items`; authoritative sell prices
come from the selected robot's inventory entry.

The visible Crop Queue is currently a frontend shell. There is no `farm` field in
the canonical world, no `PLANT` action, and no crop-growth timer. The current
`HARVEST` activity grants wheat directly. The next backend milestone is one
coordinated wheat lifecycle with shared plots, timestamped readiness, plot-aware
harvesting, events, API documentation, and exactly-once tests.

Enable deterministic backend-owned play with:

```sh
AUTONOMY_ENABLED=true AUTONOMY_PROVIDER=mock GAME_MODE=simulation \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
curl -X POST http://localhost:8000/game/start
```

Use `AUTONOMY_PROVIDER=gemini` with an exported `GOOGLE_API_KEY` for Gemini.
Autonomy is disabled by default. When enabled, planning runs only while the game
is `RUNNING`, accepted decisions appear in the shared conversation feed, and
`POST /agent-chat/round` returns `409` so a browser cannot start a second planner.
Stop, completion, or reset prevents new task dispatch; a new session clears the
orchestrator's cooldown and conversation state.

Run agent tests (mocked model responses; no billable calls):

```sh
python -m unittest discover -s tests -p 'test_agents.py' -v
```

References: [Google ADK](https://google.github.io/adk-docs/agents/llm-agents/) and
[Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).

## Live spectator conversation

Run the chat API from `backend` in a terminal with your exported Gemini API key:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in a second terminal using its README instructions. The
**Robot conversation** panel subscribes to the shared WebSocket feed and does not
choose a provider, start planning rounds, or submit proposed tasks. Configure the
backend provider with `AUTONOMY_PROVIDER`, enable it with `AUTONOMY_ENABLED=true`,
restart the backend, and start the game through the lifecycle API or UI.

Every available robot publishes one brief public `message` with its accepted
action or reason for waiting. These are intentional public coordination messages,
not private model reasoning. They appear over WebSocket within roughly half a
second and reconnecting viewers receive the latest full history.

The service keeps one shared conversation in memory, with at most 100 messages;
only the latest 20 are sent to models. A new game session clears the history, and
restarting the backend clears it too. The legacy discussion-round endpoint remains
available to direct API clients only when backend autonomy is disabled; the shipped
frontend never calls it.

Configuration:

- Backend `FRONTEND_ORIGINS`: comma-separated allowed browser origins; defaults to
  `http://localhost:5173,http://127.0.0.1:5173`.
- Frontend `VITE_API_BASE_URL`: backend URL; defaults to `http://localhost:8000`.
- Existing `GOOGLE_API_KEY`, `AGENT_MODEL`, `AGENT_TIMEOUT_SECONDS`, and
  `AGENT_INTERVAL_SECONDS` still apply. Restart the server after changing them.

Transport and payloads are documented in `api.md`. The implementation lives in
`app/agents/chat.py`, `app/api/agent_chat.py`, and `app/main.py`; it uses the existing
per-robot Gemini planner. The game `/world` and `/events` endpoints provide the
authoritative frontend state.

For the discussion preview only, the frontend's buy-only market catalog is
augmented with inventory sale items/prices in a copied snapshot. This lets agents
understand the current dashboard without changing its data. This adapter is never
used by authoritative task validation or real transaction execution.

## Live demo persistence (SQLite / Tiger Data)

The existing main-branch game loop remains authoritative. The frontend, Gemini
chat transport, task rules, map, prices, robot health and pose APIs are unchanged.
A recorder now writes every accepted world transition, its new events and changed
poses in one transaction before publishing it in memory. `mode: simulation`
means the online robots are simulated, not proof of connected physical hardware.
Simulation samples have `source: simulation`; observations submitted to the pose
endpoint have `source: pose_report` (the transport does not identify the sensor).

The older scripted cooperation/order app is preserved on `feature/backend-tigerdata`
and draft PR #1; its `/simulation/cooperation/*` controls are not mounted in this
live app. They should not replace the team's working task loop. Chat proposals
remain in the in-memory chat feed; accepted task transitions are persisted. This
slice does not record every raw Gemini response or offer exact full-state replay.

Run from `backend` (Python 3.11+):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
export SQLITE_PATH=./lovebugs.sqlite3
unset DATABASE_URL
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use one worker. Each new application instance gets a unique session ID; old
sessions remain in the database, but the game does not resume them on restart.
Read the current ID from `/world` rather than hardcoding `demo-session-001`.
World/task/pose/health/chat responses and WebSocket `/events` retain their shape.
New historical reads (oldest first within the most recent bounded results):

- `GET /events?limit=100`: persisted events for the current session.
- `GET /robots/robot-a/history?limit=100`: `session_id`, `robot_id`, `mode`,
  `position_samples` and robot-specific `events`.
- Either route accepts `session_id=...` to inspect an earlier session and a limit
  from 1 to 1000. Unknown robot/session history returns 404; an event query with no
  matches returns an empty list. Simultaneous event timestamps preserve write
  revision and event order for newly recorded data.

Historical events/poses and the latest world snapshot live in separate tables.
If a database write fails, the transition is not published and mutation APIs
return 503 `PERSISTENCE_UNAVAILABLE`; the simulator retries on its next tick.
Reads of the in-memory `/world` still work. A configured but unreachable database
prevents startup rather than silently falling back to SQLite. Tests injecting a
`WorldStore` keep their in-memory behavior unless `settings=Settings(...)` is given.

For Tiger Data, export the service's PostgreSQL connection URL locally:

```sh
export DATABASE_URL='postgresql://USER:PASSWORD@HOST:PORT/tsdb?sslmode=require'
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Do not commit the real URL. The service must have TimescaleDB 2.13+ installed and
the role must be able to create/alter/read/write tables. Initialization creates
`robot_events` and `robot_positions` hypertables; their primary keys include
`timestamp`. A regular event-ID registry enforces session-wide identity, and the
migration supports the earlier ordinary event-table primary key. There is no
Tiger API key requirement. `.env` files are not automatically loaded.

Insert/read smoke test against the running server:

```sh
curl -fsS -X POST http://localhost:8000/game/start
curl -fsS http://localhost:8000/events
curl -fsS http://localhost:8000/robots/robot-a/history
```

Expect a persisted `game_started` event and an initial position sample. Automated
verification, including an isolated-schema Tiger test when credentials are set:

```sh
.venv/bin/python -m unittest discover -s tests -v
# Optional: use a dedicated test service; requires CREATE SCHEMA permission.
export TEST_DATABASE_URL="$DATABASE_URL"
.venv/bin/python -m unittest discover -s tests -p test_persistence.py -v
PYTHONPATH=. .venv/bin/python tests/http_smoke.py
```

Without `TEST_DATABASE_URL`, the live Tiger test is skipped. SQLite checks do not
verify a real Tiger service or live Gemini access. No retention policy is set yet;
old sessions accumulate until a separate retention policy is agreed.
