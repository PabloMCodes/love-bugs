# Backend

Python 3.11+ / FastAPI / Pydantic, following [the shared contract](../api.md).
The first persistence slice runs a deterministic simulation fixture: two robots
arrive at Home (`homebase`), their meeting point. Startup atomically stores their
positions, arrival events, and a canonical READY world. The opt-in cooperation
controls below run a scripted shared-order scenario with validated agent proposals and
arrivals. This scenario uses no live AI or real driving; it has no generic task API
or background simulation clock. It is separate from the frontend/Gemini demo.

## Local setup (no credentials)

From the repository root:

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd backend
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
curl -fsS http://localhost:8000/world
curl -fsS 'http://localhost:8000/events?limit=10'
```

Expect two robots at `(50,50)`, `mode: simulation`, `revision: 1`, and two
`robot_arrived` events explicitly labelled "Simulated". `physical.online` is false:
no physical robot communication is connected. `mode: "simulation"` identifies
the world and each historical sample has `source: "simulation"`. Render a
simulation badge using `mode`; do not infer hardware connectivity from tracking.
GET requests do not append events. Restart creates a new
session and retains old database records; this slice does not resume games.
Use one worker, without reload for demos (each reload creates a new session).
SQLite defaults to `./lovebugs.sqlite3` relative to the working directory;
database files, virtual environments, and secrets are ignored by Git.

## Tiger Data

Create a Tiger Cloud PostgreSQL service and obtain its connection URL (host,
port, database, username, password, TLS settings). No Tiger API key or AI key is
needed. Use a database role allowed to create/alter the tables and indexes and
read/write them. PostgreSQL must have TimescaleDB 2.13+ installed (Tiger Data
provides it); plain PostgreSQL without the extension fails initialization. A DBA
can enable an installed extension with `CREATE EXTENSION IF NOT EXISTS timescaledb;`.
The same store and API run against SQLite or PostgreSQL; there
is no silent fallback when a configured database fails.

```sh
cd backend
# Paste the service URL privately; this avoids putting the secret in shell history.
read -r -s DATABASE_URL
export DATABASE_URL
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The URL format is `postgresql://USER:PASSWORD@HOST:PORT/tsdb?sslmode=require`.
Percent-encode special characters in URL credentials. Follow the service's TLS
settings, including certificate verification when configured. See
[Tiger connection details](https://docs.tigerdata.com/use-timescale/latest/integrations/find-connection-details/).
Never commit the real URL. `.env.example` documents variables but the app does
not auto-load `.env`; export variables in the launching shell.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | unset | Tiger/PostgreSQL URL; unset selects SQLite |
| `SQLITE_PATH` | `./lovebugs.sqlite3` | Local persistent database path, not `:memory:` |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | Allowed browser HTTP origin |
| `TEST_DATABASE_URL` | unset | Optional dedicated test database URL |

### Live insert/read smoke test (not yet verified here)

Use a dedicated Tiger Data test service with TimescaleDB enabled. The test role
must also be allowed to create/drop a schema. From the repository root, after
installing dependencies:

```sh
cd backend
# Paste the test service URL at the hidden prompt, then press Enter.
read -r -s TEST_DATABASE_URL
export TEST_DATABASE_URL
.venv/bin/python -m unittest discover -s tests -p 'test_backend.py' -k test_postgres -v
```

Expected: `test_postgres ... ok`, not `skipped`. The test creates a unique schema,
seeds legacy ordinary tables, converts them without losing data, verifies both
hypertables in `timescaledb_information.hypertables`, inserts simulated samples
and events, reads them back through the history query, and checks event-ID
uniqueness across timestamps. It drops only its own schema on completion.
No test URL means the test is skipped; passing SQLite checks is not evidence
of a live Tiger Data connection.

To launch the app against that same test service and inspect the HTTP response:

```sh
export DATABASE_URL="$TEST_DATABASE_URL"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then, in another terminal:

```sh
curl -fsS 'http://localhost:8000/robots/robot-a/history?limit=10'
```

This server startup writes a new session in the application's default schema;
its data remains after shutdown, unlike the isolated smoke-test schema.

## Frontend contract: implemented subset

- `GET /world`: exact canonical world shape in `api.md`; latest 100 semantic events, oldest first.
- `GET /events?limit=100`: additive HTTP read endpoint; `{session_id, events}` with
  1–100 most recent current-session events, oldest first. Equal timestamps sort by
  event ID. Event fields remain `id, timestamp, type, robot_id, task_id, message, data`.
- `GET /robots/{robot_id}/history?limit=100`: current-session history for that robot.
  `limit` bounds each of `position_samples` and `events` independently (1–1000),
  selecting the most recent records and returning each list oldest first.
  Unknown robot: 404; invalid limit: 400; storage unavailable: 503. Events with
  null/other robot IDs are excluded; use `/events` for the full feed.
- WebSocket `/events`: initial `{type: "world_snapshot", data: <entire world>}`,
  followed by changed revisions, checked at 5 Hz. Mutations occur only when simulation controls are called.

History response (startup has one sample per robot; later adapter samples form a path):

```json
{
  "session_id": "<current-session>",
  "robot_id": "robot-a",
  "mode": "simulation",
  "position_samples": [{
    "session_id": "<current-session>", "robot_id": "robot-a",
    "timestamp": "2026-09-26T12:00:00Z", "source": "simulation",
    "pose": {"x": 50, "y": 50, "heading": 0}
  }],
  "events": [{
    "id": "<event-id>", "timestamp": "2026-09-26T12:00:00Z",
    "type": "robot_arrived", "robot_id": "robot-a", "task_id": null,
    "message": "Simulated Billy is at Home, the meeting point.",
    "data": {"location": "homebase", "source": "simulation", "initial": true}
  }]
}
```

The frontend can draw a trail from `position_samples[].pose` and display the
associated timeline without reconstructing authoritative game state.
`/world` keeps its existing shape; no frontend files were changed.

The HTTP and WebSocket routes can share `/events`. Frontend can poll `/world`
or use snapshots with the existing session/revision rules. Pose samples never
appear in the event feed. Failures use the shared error envelope; bad query
fields return 400, unavailable persistence returns 503. Startup fails if storage
cannot initialize. All other proposed routes in `api.md` remain unimplemented.
Local demo only; authentication and deployment hardening are not implemented.

## Small data model and integration boundary

| Table | Fields / responsibility |
| --- | --- |
| `world_state` | `session_id` primary key, canonical JSON `snapshot` excluding feed. One latest state per session, separate from history. |
| `robot_positions` | `(session_id, robot_id, timestamp)` primary key; `source`, normalized `x, y, heading`. UTC timestamped telemetry. |
| `robot_events` | `(session_id, id, timestamp)` primary key for new tables; UTC `timestamp`, `type`, nullable `robot_id/task_id`, `message`, JSON `data`. Semantic history. |
| `cooperation_state` | Current JSON objective, message exchange, arrival confirmations, and task history per session; committed atomically with world/history. |
| `event_ids` | `(session_id, id)` primary key in a regular table; preserves session-wide event-ID uniqueness independently of time partitioning. |

The existing SQL names `robot_positions` and `robot_events` are retained to
preserve first-slice databases. `position_samples` is the history API field.

JSON is stored as text for the thin cross-database implementation. PostgreSQL
uses TIMESTAMPTZ; SQLite stores timezone-qualified ISO strings. Producers should
use UTC (the store normalizes writes). Event timestamps plus ID provide stable
feed ordering. PostgreSQL startup converts both historical tables into
hypertables partitioned on `timestamp` using `create_hypertable`,
`by_range('timestamp')`, `if_not_exists => true`, and `migrate_data => true`.
Current state and event identities remain ordinary tables. SQLite does not run
any Timescale SQL and existing SQLite databases keep their original event key.

Initialization backfills event identities, replaces the legacy PostgreSQL event
primary key with one including `timestamp`, and migrates existing rows, all in
one transaction. Repeated initialization preserves data. This targets the first
slice's known schema; unexpected constraints cause a rollback instead of data
loss. Migration is serialized with a PostgreSQL advisory lock. Conversion can
lock populated tables: perform the first migration with other writers stopped.
No automatic retention/deletion policy is configured, including for old sessions.

These choices follow Tiger Data's [hypertable conversion documentation](https://github.com/timescale/Tiger-Data-Docs/blob/main/src/content/docs/learn/hypertables/creating-and-configuring-hypertables.mdx)
and [unique-index requirements](https://github.com/timescale/Tiger-Data-Docs/blob/main/src/content/docs/build/performance-optimization/hypertables-and-unique-indexes.mdx):
all unique keys on a hypertable must include its partition columns.

`Store.commit(world, events, positions)` is the single transactional persistence
boundary. Simulation uses it now; future game logic and validated localization
adapters can use it without changing the frontend shape. Callers serialize game
mutations and validate session/task identity, arrival, freshness, resources, and
cooperation before committing. Duplicate IDs fail and roll back the whole batch;
this is not yet a retry/deduplication service. There is no public raw event-write
endpoint or way to award resources through this slice.

Suggested event payloads for later producers (not new executable actions):

| Type | `data` |
| --- | --- |
| `agent_decision` | action, location, parameters, reason |
| `robot_arrived` | location, source; task_id in the event when task-driven |
| `inventory_updated` / `gold_updated` | item when applicable, delta, resulting quantity/balance |
| `help_requested` / `help_accepted` | objective_id, participant_ids, location: homebase |

Task IDs correlate decisions and arrivals; objective IDs correlate cooperation.
Do not infer current state by replaying arbitrary feed payloads. Home is the
meeting point; confirming both arrivals and applying one cooperative reward
belongs to deterministic game rules, not persistence or an AI. Overhead-camera
localization is separate from ESP32 cameras; neither is integrated here.

## Scripted caring scenario

Pressing start represents the human giving Billy and Milo a fixed order:
bring **one wheat and one fish Home**, earning **10 shared gold (5 each)**.
Billy starts at the farm with one wheat and a `FULFILL_ORDER` task. Milo starts
at the lake with a fish and a planned `SELL` task. These are explicit simulation
fixtures, not observed harvesting or fishing. Billy discovers that his wheat
alone cannot fulfill the order, sends a structured request, and Milo chooses
`HELP_PARTNER` over his possible individual sale (12 gold by default).

After both validated arrivals, one transaction transfers the fish, consumes one
wheat and one fish, completes the order, and credits 5 gold to each robot. No
meal or other item is produced. The unexecuted sale never credits or debits gold.
Both wallets remain 40 through arrival and become 45 on completion. The existing
sum-of-wallets `game.goal.current` increases from 80 to 90; its earn-gold type and
500 target remain unchanged. Game status remains RUNNING because that goal is
not yet reached. Read `objective.phase` for the order's COMPLETED state.

Endpoints, phases, command bodies and response envelopes are unchanged.
`FULFILL_ORDER` replaces the former `PREPARE_MEAL` action; `HELP_PARTNER` remains.
Task fields and the per-robot proposal/message interfaces are unchanged. The
standalone Gemini/ADK planner described below is preserved but is not connected
to this scenario; the cooperation demo uses its deterministic fallback policy.

### Frontend controls

| Method / endpoint | Request | Response |
| --- | --- | --- |
| `GET /simulation/cooperation` | none | `{world, objective, policy}` |
| `POST /simulation/cooperation/start` | command below | same envelope |
| `POST /simulation/cooperation/advance` | command below | same envelope; one phase per call |
| `POST /simulation/cooperation/reset` | command below | new session in READY; `objective: null` |

Every POST requires current values from `world`:

```json
{"session_id": "<world.session_id>", "expected_revision": 1}
```

Stale session/revision or an invalid phase returns 409 with
`{error: {code: "INVALID_STATE", message}}`. Read again after 409; never blindly
retry an old advance. Bad fields return 400. Further advances after completion
are rejected. Controls reject hardware mode. Run one worker: a lock serializes
scenario operations, and each mutation commits world, objective, events, and
pose samples together on SQLite or Tiger Data.

`world` remains the canonical snapshot returned by `/world` and the WebSocket.
`objective` is null before start/reset, otherwise:

- `id`: shared objective ID, also in event `data.objective_id`.
- `phase`: see sequence below.
- `arrived`: robot IDs with validated Home arrivals for this objective.
- `messages`: `HELP_REQUESTED` / `HELP_ACCEPTED` messages containing `session_id`,
  `objective_id`, `request_id`, `sender_id`, `recipient_id`, `item`, `quantity`, `reason`.
- `tasks`: canonical task history, including the cancelled sale and completed tasks.
- `forgone_sale_value`: null before acceptance; market fish sale value afterward.
- `requirements`: `{"wheat": 1, "fish": 1}`.
- `reward_gold`: `10`; `reward_split`: `{"robot-a": 5, "robot-b": 5}`.

`policy` is `"deterministic"`; label the demo as scripted simulation, never live
AI. The WebSocket carries only canonical world snapshots. Refresh objective
information through the control response or GET above.

| Call | Phase | What happens |
| --- | --- | --- |
| start | ASSIGNED | Human order is issued; Billy gets FULFILL_ORDER; Milo plans a fish sale |
| advance 1 | HELP_REQUESTED | Billy asks Milo for one fish |
| advance 2 | HELP_ACCEPTED | Milo chooses HELP_PARTNER, cancels SELL, records forgone gold |
| advance 3 | TRAVELING_HOME | Both depart; the map shows intermediate simulated poses |
| advance 4 | ONE_ARRIVED | Billy's arrival is validated |
| advance 5 | BOTH_ARRIVED | Milo's arrival is validated; he still owns the fish |
| advance 6 | COMPLETED | Resources are consumed and the shared gold reward is paid atomically |

Render `world.events[].message` for the story. Each scenario event also carries
`data.reason`. Main event types: `help_requested`, `agent_decision`,
`help_accepted`, `traveling_home`, `robot_arrived`, `resource_shared`, and
`joint_task_completed`. `agent_decision.data.forgone_sale_value` explains the
opportunity cost; no money is deducted. `resource_shared.data` records giver,
receiver, quantity and immediate balances. The same transaction consumes the
fish and wheat, so the final world shows depleted resources and rewarded
wallets, not an intermediate fish in Billy's pocket. Two `gold_updated` events
record `delta: 5`, `balance: 45`, and `source: "shared_order_reward"`.
`joint_task_completed.data` keeps `consumed` and now has `produced: {}`,
`reward_gold: 10`, and `reward_split`. The old `owner_robot_id` is removed
because this is a shared order, not an item belonging to Billy. Existing robot history reads show the travel samples.

Arrival rules validate session, task, destination, sample identity, increasing
and fresh pose time, Home coordinates (one world unit tolerance per axis), and
stopped/blocked flags. Duplicate accepted arrivals are idempotent. Handoff
requires both confirmed arrivals, both still at Home with active tasks, and
available resources. An early handoff fails without inventory changes. The
simulator leaves arrived robots at rest; a real adapter must keep localization
and tracking freshness current.

Reset atomically creates a fresh world with reset events, then replaces the
active session. It clears resources/tasks/messages and invalidates old commands
and reports. Prior sessions remain frozen in historical storage; there are no
background movement jobs. WebSockets detect a new session even at an equal
revision. Server restart also creates a fresh session as before.

### Run the full sequence

Start the server as described above. From `backend/`, in another terminal:

```sh
.venv/bin/python - <<'PY'
import json
from urllib.request import Request, urlopen
base = "http://localhost:8000/simulation/cooperation"
with urlopen(base) as response:
    state = json.load(response)
for operation in ["reset", "start"] + ["advance"] * 6:
    command = {"session_id": state["world"]["session_id"],
               "expected_revision": state["world"]["revision"]}
    request = Request(base + "/" + operation, data=json.dumps(command).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request) as response:
        state = json.load(response)
    print(operation, state["objective"]["phase"] if state["objective"] else "READY")
for event in state["world"]["events"]:
    print(event["message"])
print([(r["name"], r["game"]) for r in state["world"]["robots"]])
print("Shared gold goal:", state["world"]["game"]["goal"])
PY
```

### Frontend change list: shared order revision

No `/world` fields were added or removed, and no endpoint or phase names changed.
The values that changed are:

| Field | Previous demo | Shared-order demo |
| --- | --- | --- |
| Billy `robots[].task.action` | `PREPARE_MEAL` | `FULFILL_ORDER` (still null after completion) |
| `robots[].task.reason` | Meal/sale explanations | Order/sale explanations below |
| Billy `robots[].game.inventory` at completion | wheat 0, fish 0, meal 1 | wheat 0, fish 0; no meal key |
| Each robot `robots[].game.money` at completion | 40 | 45; unchanged until completion |
| `game.goal.current` at completion | 80 | 90 (sum of current wallets) |
| `events[].message` and `events[].data.reason` | Meal story | Exact copy below |

Milo's final inventory is still `{"fish": 0}`. Goal type/target, positions,
physical status, schema version and task field shapes are unchanged. Normal
revision/timestamp updates still happen on each step. Reset returns wallets to
40, goal current to 80, and inventories to empty objects in a new session.
Outside `/world`, `objective` adds `requirements`, `reward_gold`, and `reward_split`.

Changed event copy (robot names and market price are interpolated):

| Event | New `message` (also copied to `data.reason`) |
| --- | --- |
| `scenario_started` | A new order from you: bring one wheat and one fish Home! Billy and Milo can earn 10 gold together. |
| `task_assigned` (Billy) | Billy will bring his wheat Home to fulfill your order. He still needs a fish from a partner. |
| `task_assigned` (Milo's SELL) | Milo has a fish and plans a little market trip to sell it. |
| `help_requested` | Milo, I have the wheat for our order, but I cannot finish it alone. Could you bring a fish Home? |
| `agent_decision` | Milo chooses HELP_PARTNER: our order comes first! He passes up a possible 12 gold sale to bring Billy a fish. |
| `task_cancelled` | Milo sets his market trip aside. The fish is for our order; no sale gold changes hands. |
| `help_accepted` and Milo's HELP_PARTNER `task_assigned` | On my way, Billy! I will bring my fish Home for our order instead of selling it. |
| `traveling_home` | {name} heads Home with their contribution. Time to bring our order together! |
| `robot_arrived` (during order) | {name} is Home with their contribution to the order. One step closer, together! |
| `resource_shared` | Milo hands Billy a fish at Home. With Billy's wheat, our order has everything it needs! |
| `task_completed` | {name} completed their part of our order. Nice teamwork! |
| `gold_updated` (new, one per robot) | {name} receives 5 gold as their share of the order reward. |
| `joint_task_completed` | Order complete! One wheat, one fish, and a little teamwork. Billy and Milo share 10 gold, 5 each! |

Startup arrivals and inventory setup messages are unchanged. Reset's message is
unchanged, but its `data.reason` is now "Start a fresh shared order without
retaining resources or rewards." Agent message reasons match request/acceptance
copy. `scenario_started.data` adds `issued_by: "human"`, `requirements`,
`reward_gold`, and `reward_split`. Billy's `task_assigned.data.action` changes to
`FULFILL_ORDER`. Completion/reward payload changes are described above; existing
`objective_id`, correlation IDs, consumed resources and transfer balances remain.
Old sessions/events are retained as historical records and are not rewritten.

### Agent and robot integration boundaries

- `app/agents/protocol.py`: typed actions/messages and the per-robot `RobotAgent`
  interface. Each agent gets a detached world/objective view and its addressed
  inbox. The persisted exchange supplies this demo's agent memory.
- `app/agents/planner.py`: separate deterministic policy instances for Billy and
  Milo. A future Gemini adapter can implement `propose(context)` and return the
  same validated `AgentAction`; policies cannot directly transfer resources.
- `app/game/cooperation.py`: policy-independent action/message, arrival, handoff,
  and order rules. Proposals are scoped to session/objective IDs.
- `app/simulation/cooperation.py`: manual clock, simulated pose production and
  serialized persistence. A future navigation/localization adapter can deliver
  `ArrivalReport` to these same rules through a serialized service boundary.
  No public arrival endpoint or ESP32 transport is implemented yet.

Run `.venv/bin/python -m unittest discover -s tests -v`. Tests cover the full
sequence, early handoff, invalid/duplicate arrivals, missing resources, unmatched
messages, reset/stale commands, reset after payout, WebSocket resets, and rollback of resource
consumption and rewards after a final
transaction-write failure. Live Tiger checks still require `TEST_DATABASE_URL`;
SQLite passes do not establish cloud connectivity.

Next ticket: add the real arrival adapter with tracking freshness and
cancellation, retaining a simulated partner. Gemini can then replace the
scripted proposal policy without changing the transfer rules.

## Standalone overhead vision

Vision is implemented independently of the placeholder backend server. Requires Python 3.10+.
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

This explicit mock policy proposes harvesting for Billy and fishing for Milo.
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

The frontend currently owns a separate mock simulation on `dev`; this module
is not wired to it. Numeric inventory counts from `api.md` and the frontend's
`{quantity, name, sell_price}` entries are both readable, but authoritative trade
prices always come from `world.market.items`. A shared backend task service and
world feed are the next integration step; no frontend contract was changed here.

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

Start the frontend in a second terminal using its README instructions. In the
**Robot conversation** panel, choose **Mock demo** or **Gemini agents**, then
**Start chat**. Pause stops future rounds; an in-flight round may finish. Gemini
mode makes paid/quota-counted calls; mock mode is explicitly scripted. No model
calls happen until a browser starts the conversation. The key stays on the backend.

Each round sends the current frontend simulation snapshot to the local backend.
Every available robot proposes one action and a brief public `message` to its
teammates. The second robot receives the first robot's message before answering;
the next round includes the recent conversation, so both robots can respond.
These are intentional public coordination messages, not private model reasoning.
They appear over WebSocket within roughly half a second of each model response.

The chat backend only proposes actions. On current `main`, the frontend consumes
new proposals while chat is enabled and dispatches supported movement/collection
actions into its own simulation. Proposals can be ignored by frontend validation;
`status: proposed` is not proof of execution. The backend chat service itself does
not mutate either game loop. READY and RUNNING games may discuss; stopped,
completed, busy, offline, or untracked robots are skipped. For the current demo, the frontend remains the source of truth; the proposed next
step is recording its outcomes without replacing its simulation. The existing `AgentOrchestrator`
also feeds recent messages into decisions and publishes messages only for accepted
tasks or WAIT decisions. Rejected decisions are never presented as accepted work.

The service keeps one shared conversation in memory, with at most 100 messages;
only the latest 20 are sent to models. A new game session or provider switch clears
the history. Restarting the backend clears it too. One browser should operate the
Start/Pause controls; other browsers can watch the same live feed without starting
another loop. Concurrent rounds are rejected, and the default 10-second cooldown
is enforced server-side. Browser rounds wait at least 12 seconds after completion.
Model errors pause that browser's loop and display a redacted error, without
fabricating chat messages. Reconnecting viewers receive the latest full history.

Configuration:

- Backend `FRONTEND_ORIGINS`: comma-separated allowed browser origins; defaults to
  `http://localhost:5173,http://127.0.0.1:5173`.
- Frontend `VITE_API_BASE_URL`: backend URL; defaults to `http://localhost:8000`.
- Existing `GOOGLE_API_KEY`, `AGENT_MODEL`, `AGENT_TIMEOUT_SECONDS`, and
  `AGENT_INTERVAL_SECONDS` still apply. Restart the server after changing them.

Transport and payloads are documented in `api.md`. The implementation lives in
`app/agents/chat.py`, `app/api/agent_chat.py`, and `app/main.py`; it uses the existing
per-robot Gemini planner. The game `/world` and `/events` endpoints coexist with chat in the combined app.

For the discussion preview only, the frontend's buy-only market catalog is
augmented with inventory sale items/prices in a copied snapshot. This lets agents
understand the current dashboard without changing its data. This adapter is never
used by authoritative task validation or real transaction execution.

## Combined API verification

The combined app preserves the cooperation and spectator-chat paths and response
formats. Game errors use `{ "error": { "code": ..., "message": ... } }`;
chat retains FastAPI's `detail` errors (including 422 for invalid requests).
Chat remains a separate, in-memory discussion preview and does not execute orders.
Startup initializes game persistence even when only chat is used; SQLite is the
default when `DATABASE_URL` is unset. Each server start creates a new game session.

Factory callers can use `create_app(Settings(...))`, `create_app(service)`, or
`create_app(service=..., settings=...)`. `FRONTEND_ORIGINS`, when set, takes
precedence over `FRONTEND_ORIGIN`; otherwise the singular setting is supported,
with both localhost aliases allowed for the default development origin.

From `backend`, verify the combined app without external credentials:

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=. .venv/bin/python tests/http_smoke.py
```

The smoke test starts a temporary localhost server with SQLite and mock chat. It
checks `/world`, cooperation start/advance/reset, HTTP and WebSocket `/events`,
and spectator-chat GET/POST/WebSocket endpoints. Concurrent final advances must
produce one success and one conflict, award 5 gold to each robot exactly once,
and reject another completion. Reset restores the fixture in a new session.
This does not verify a live Tiger Data connection or make Gemini calls; the
PostgreSQL integration test requires `TEST_DATABASE_URL` as documented above.


## Proposed bridge for the current frontend demo (not implemented)

As of `main` commit `9d94d70`, P/J's frontend owns simulation state and dispatches
chat proposals. The backend cooperation endpoints are a separate scripted demo,
not a recording of their Gemini flow. Keep `/world` and cooperation controls
separate from any future imported session; do not point their UI at our fixture.

The smallest bridge is an additive ingestion endpoint accepting batches of the
existing frontend events and changed poses, plus separately labelled agent
proposals. Preserve producer session IDs, revisions, timestamps and payloads.
Use a unique run ID (the current frontend fixture reuses `demo-session-001`),
retry-safe event IDs, and correlation from proposal ID to accepted task ID.
Recording failures should not block their simulation. Confirm the host, transport,
retry ownership, coordinate frame and a real payload before implementing it.

Existing events already have `id`, `timestamp`, `type`, `robot_id`, `task_id`,
`message`, and `data`. World snapshots contain session/revision and poses with
`pose_updated_at`. Chat messages instead use `text`, `action`, `location`, and
`status`; they need a labelled mapping, not an assumption that proposals executed.
Frontend inventories are item objects (including quantity and price), and its map
and prices differ from the backend fixture. Preserve these values in recordings.

The store supports transactional events/poses and SQLite or Tiger hypertables,
but has no public ingestion API. Duplicate batches currently fail rather than
acknowledge retries; public history reads only the backend's current session.
An adapter needs isolated imported sessions, idempotent ingestion, ordering and
session-selectable reads. Exact replay also needs an initial snapshot plus
complete ordered changes or revision snapshots: the current event feed is capped
at 100, event timestamps can tie, and events alone omit some state. The store's
latest-only world snapshot does not provide full replay today.

Wait for one captured real world/event/chat payload bundle before implementing.
No ingestion route or change to P/J's simulation is included in this PR.
