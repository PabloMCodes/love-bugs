# Game and robotics API contract

Status: **stable MVP v1 application contract**. The authoritative world feed,
goal and lifecycle controls, all documented task actions, read-only queries,
history, and robotics-ingestion routes are implemented and tested. Teammates may
build against the HTTP paths, payloads, error meanings, world schema, and WebSocket
envelope below. Existing fields and meanings require a coordinated contract
change; additive endpoints and event types are allowed. Physical hardware adapters
remain integration work and the provisional ESP32 transport is not frozen.

For the practical subsystem handoff and acceptance checks, see
[INTEGRATION.md](INTEGRATION.md). For gameplay direction, milestone scope, and
the target demo scenario, see [GAME_PLAN.md](GAME_PLAN.md). The planned farming,
fishing, and cooperative economy are recorded in [GAME_DESIGN.md](GAME_DESIGN.md).
Neither planning document changes this contract by itself; planned contract
changes still require coordinated updates to this document, tests, and consumers.

Contract version 1 permits additive endpoints, optional response fields, and event
types. Do not remove or rename fields, change their types or meanings, or alter an
existing route's behavior without coordinating every affected subsystem and
updating this document, examples, tests, and consumers in the same change. A
breaking world-schema revision must increment `schema_version`.

No teammate assignments, language, framework, agent provider, or hardware transport are prescribed here. Responsibilities below belong to subsystems, and teammates can decide who implements them.

## Architecture and scope

```text
Frontend ← REST / WebSocket → Game + agent backend
                                      ↕
                              Navigation controller → ESP32 robots
                                      ↑
Overhead camera → Localization → shared world state
```

The backend owns game state, inventory, gold, tasks, destinations, decisions, and events. Agents select restricted high-level actions. Navigation translates destinations into movement; only deterministic control code generates motor commands. The frontend communicates with the backend, never directly with ESP32 devices.

The MVP has two robots and four locations: `homebase`, `farm`, `lake`, `market`. A third robot, onboard video, additional locations, and advanced mechanics are optional. Clients must render the returned robot list rather than assume particular names or exactly two entries.

## Development defaults

- HTTP base URL: `http://localhost:8000`
- WebSocket URL: `ws://localhost:8000/events`
- Runtime mode: `GAME_MODE=simulation` by default; set `GAME_MODE=hardware` before
  starting the backend to disable generated movement and wait for adapter telemetry.
- JSON request and response bodies; requests with bodies use `Content-Type: application/json`.
- Configure connection URLs in the chosen implementation; do not hardcode robot IP addresses in the frontend.
- `/world` and `/events` are the canonical names, consistent with `AGENTS.md`. Earlier draft names `/state` and `/ws` are not required aliases.
- The backend should allow the chosen local frontend origin during development.

## Shared conventions

| Field | Contract |
| --- | --- |
| IDs | Opaque strings. Robot IDs are stable; task and event IDs are unique within a game session. |
| Time | UTC ISO 8601 strings, for example `2026-09-25T14:00:00.000Z`. |
| Position | UI/world coordinates from 0 to 100 on each axis; origin at top left, x increases right, y increases down. Localization/navigation adapters convert physical units to and from this space. |
| Heading | Degrees in `[0, 360)`: 0 points right, 90 points down, increasing clockwise. |
| Progress | Number from 0 to 1. |
| Money and quantities | Nonnegative integers. Requests to buy/sell require a positive integer quantity. |
| Unknown values | Explicit `null`; never invent a position or battery reading. |
| Inventory | Object from stable item ID to `{ "name", "quantity", "sell_price" }`; an omitted item has quantity zero. |
| Location | Named zone when confirmed inside it; `null` between zones or when unknown. |

Proposed gameplay defaults: each robot has its own wallet and inventory; the shared goal counts the sum of current wallet balances. Spending can therefore reduce goal progress. Prices, starting balances, activity durations, and rewards below are demo values, not final balancing decisions. The server supplies them or the resulting state; clients must not calculate authoritative rewards or balances.

## Canonical world snapshot

`GET /world` returns `200` with this complete shape. The same shape is used in WebSocket snapshots and simulation. This example represents a running simulation; seed values are illustrative.

```json
{
  "schema_version": 4,
  "session_id": "session-001",
  "revision": 12,
  "updated_at": "2026-09-25T14:00:00.000Z",
  "mode": "simulation",
  "game": {
    "status": "RUNNING",
    "goal": { "type": "earn_gold", "target": 200, "current": 80 },
    "stage": 1
  },
  "map": {
    "width": 100,
    "height": 100,
    "locations": {
      "homebase": { "x": 50, "y": 50 },
      "farm": { "x": 20, "y": 30 },
      "lake": { "x": 70, "y": 80 },
      "market": { "x": 80, "y": 40 }
    }
  },
  "robots": [
    {
      "id": "robot-a",
      "name": "Wall-y",
      "physical": {
        "online": true,
        "pose": { "x": 20, "y": 30, "heading": 90 },
        "pose_updated_at": "2026-09-25T14:00:00.000Z",
        "tracking": "TRACKED",
        "battery": null,
        "blocked": false,
        "stopped": false
      },
      "game": {
        "location": "farm",
        "money": 40,
        "inventory": {
          "wheat": { "name": "Wheat", "quantity": 2, "sell_price": 12 },
          "seeds": { "name": "Wheat Seeds", "quantity": 1, "sell_price": null }
        }
      },
      "task": {
        "id": "task-001",
        "robot_id": "robot-a",
        "action": "HARVEST",
        "location": "farm",
        "status": "ACTIVE",
        "progress": 0.67,
        "parameters": { "plot_id": "plot-1" },
        "reason": "Harvest wheat to sell at the market.",
        "error": null
      }
    },
    {
      "id": "robot-b",
      "name": "Eeva",
      "physical": {
        "online": true,
        "pose": { "x": 50, "y": 50, "heading": 0 },
        "pose_updated_at": "2026-09-25T14:00:00.000Z",
        "tracking": "TRACKED",
        "battery": null,
        "blocked": false,
        "stopped": false
      },
      "game": {
        "location": "homebase",
        "money": 40,
        "inventory": {}
      },
      "task": null
    }
  ],
  "market": {
    "items": [
      { "id": "seeds", "name": "Wheat Seeds", "buy_price": 5, "sell_price": null, "stock": null, "required_stage": 1, "unlock_at": null },
      { "id": "carrot_seeds", "name": "Carrot Seeds", "buy_price": 10, "sell_price": null, "stock": null, "required_stage": 2, "unlock_at": 100 },
      { "id": "pumpkin_seeds", "name": "Pumpkin Seeds", "buy_price": 20, "sell_price": null, "stock": null, "required_stage": 3, "unlock_at": 150 }
    ]
  },
  "farm": {
    "crops": [
      { "id": "wheat", "name": "Wheat", "seed_item_id": "seeds", "grow_seconds": 8, "harvest_quantity": 3, "sell_price": 12, "required_stage": 1 },
      { "id": "carrot", "name": "Carrots", "seed_item_id": "carrot_seeds", "grow_seconds": 12, "harvest_quantity": 3, "sell_price": 20, "required_stage": 2 },
      { "id": "pumpkin", "name": "Pumpkins", "seed_item_id": "pumpkin_seeds", "grow_seconds": 18, "harvest_quantity": 3, "sell_price": 32, "required_stage": 3 }
    ],
    "plots": [
      { "id": "plot-1", "status": "READY", "crop_id": "wheat", "planted_by": "robot-a", "planted_at": "2026-09-25T13:59:45.000Z", "ready_at": "2026-09-25T13:59:53.000Z" },
      { "id": "plot-2", "status": "EMPTY", "crop_id": null, "planted_by": null, "planted_at": null, "ready_at": null },
      { "id": "plot-3", "status": "EMPTY", "crop_id": null, "planted_by": null, "planted_at": null, "ready_at": null }
    ]
  },
  "fishing": {
    "min_duration_seconds": 5,
    "max_duration_seconds": 15,
    "tiers": [
      { "id": "common_fish", "name": "Common Fish", "sell_price": 1, "probability": 0.70 },
      { "id": "uncommon_fish", "name": "Uncommon Fish", "sell_price": 5, "probability": 0.25 },
      { "id": "rare_fish", "name": "Extremely Rare Fish", "sell_price": 15, "probability": 0.05 }
    ]
  },
  "economy": {
    "unlocks": [
      { "stage": 2, "item_id": "carrot_seeds", "item_name": "Carrot Seeds", "eligibility_gold": 100, "cost": 30, "unlocked": false },
      { "stage": 3, "item_id": "pumpkin_seeds", "item_name": "Pumpkin Seeds", "eligibility_gold": 150, "cost": 60, "unlocked": false }
    ],
    "unlock_proposals": [],
    "money_requests": [],
    "transfers": []
  },
  "events": [
    {
      "id": "event-001",
      "timestamp": "2026-09-25T13:59:58.000Z",
      "type": "task_started",
      "robot_id": "robot-a",
      "task_id": "task-001",
      "message": "Wall-y started harvesting wheat.",
      "data": {}
    }
  ]
}
```

- `mode`: `simulation` or `hardware`, selected when the backend process starts.
  Simulation must be visibly identifiable in the UI. Hardware mode never generates
  poses or arrivals; backend-owned activity timers still run after confirmed arrival.
- `game.status`: `READY`, `RUNNING`, `STOPPED`, or `COMPLETED`.
- `revision`: increases on each published state change within a session. Reset creates a new `session_id` and restarts revision numbering.
- Every endpoint returning a robot uses the canonical robot shape above. `task` is the current nonterminal task or `null`; terminal tasks remain available in task history.
- `physical.online` describes robot communication; `tracking` independently describes localization: `TRACKED`, `STALE`, or `UNKNOWN`. Initially pose and pose timestamp are `null`, and tracking is `UNKNOWN`. A stale pose may remain for display but must not be treated as fresh control input. The hardware adapter defines and documents its freshness threshold before live driving.
- `battery` is a fraction from 0 to 1 or `null`. `stopped` is a latched control stop, not an indication that the wheels happen to be stationary.
- The market list contains items visible in the shop. `game.stage` is permanent within a session and begins at 1. An item is purchasable only when `game.stage >= required_stage`; `unlock_at` mirrors the eligibility threshold for display and does not advance the stage by itself. Inventory entries contain their execution-time `sell_price`; `null` means that item cannot be sold. `stock: null` means unlimited shop stock; zero means sold out. MVP inventory has no capacity limit.
- `farm.crops` is the authoritative crop catalog. `farm.plots` contains three shared plots; nonempty plots reference a crop and planter by stable ID and carry backend-owned timestamps.
- `fishing` is the authoritative attempt-duration and reward catalog. Tier
  probabilities total 1; clients render these values but never choose a reward.
- `economy.unlocks` defines the eligibility and paid cost for each later stage.
  Proposal, money-request, and transfer arrays retain the current session's
  canonical transaction history. Clients must not infer an unlock from gold alone.
- `events` contains the latest 100 semantic events, oldest first. Pose samples are not feed events. Event `robot_id` and `task_id` may be `null`. `data` contains optional details; the UI can always display `message`.

## Frontend-facing HTTP API

Routes below are the proposed MVP surface. Empty request bodies are shown as “none.” All writes return after server acceptance or state mutation; acceptance does not mean physical completion.

| Method and path | Request | Success response |
| --- | --- | --- |
| `GET /world` | none | `200`: canonical world snapshot |
| `GET /robots` | none | `200`: `{ "robots": [...] }`, canonical robots |
| `GET /robots/{id}` | none | `200`: canonical robot |
| `GET /market` | none | `200`: canonical market object |
| `GET /economy` | none | `200`: canonical economy object |
| `POST /economy/transfers` | direct transfer request below | `201`: canonical transfer |
| `POST /economy/money-requests` | money request below | `201`: canonical pending money request |
| `POST /economy/money-requests/{id}/respond` | economy response below | `200`: accepted or rejected money request |
| `POST /economy/unlock-proposals` | stage proposal below | `201`: canonical pending unlock proposal |
| `POST /economy/unlock-proposals/{id}/respond` | economy response below | `200`: pending, completed, or rejected proposal |
| `POST /goal` | `{ "type": "earn_gold", "target": 500 }` | `200`: updated goal object; allowed only in `READY`, with a target above current gold |
| `POST /game/start` | none | `200`: world snapshot; starts from `READY`, resumes from `STOPPED` |
| `POST /game/stop` | none | `200`: world snapshot after stop is latched |
| `POST /game/reset` | none | `200`: new session snapshot in `READY` |
| `POST /robots/{id}/stop` | none | `200`: canonical robot after stop is latched |
| `POST /robots/{id}/resume` | none | `200`: canonical robot with stop latch cleared; requires a running game and healthy robot |
| `POST /tasks` | task request below | `202`: canonical task in `ASSIGNED` |
| `GET /tasks` | none | `200`: `{ "tasks": [...] }`, all tasks in current session, creation order |
| `GET /tasks/{id}` | none | `200`: canonical task, including terminal results |

Repeated start while running and repeated stops succeed without repeating side effects. Starting a completed game returns `409`; reset first. Reset cancels work and stops the fleet before clearing game state. In hardware mode it does not teleport robots or assert that they are at home; preserve actual telemetry and await fresh localization. In simulation, reset may place them at home.

### Cooperative economy

Economy commands are separate from physical tasks because they do not require a
destination or occupy a robot. Every body carries a stable `request_id`. Retrying
the identical command returns its existing result; reusing the ID for different
data returns `409 REQUEST_ID_CONFLICT`.

Direct transfer:

```json
{
  "request_id": "transfer-001",
  "sender_id": "robot-a",
  "recipient_id": "robot-b",
  "amount": 10,
  "purpose": "Help buy carrot seeds"
}
```

Money request:

```json
{
  "request_id": "money-request-command-001",
  "requester_id": "robot-a",
  "recipient_id": "robot-b",
  "amount": 10,
  "purpose": "Fund my proposed contribution"
}
```

Only the named recipient may answer a pending money request. The same response
shape is used to answer a stage proposal:

```json
{
  "request_id": "response-001",
  "robot_id": "robot-b",
  "accepted": true
}
```

A robot may have only one pending outgoing money request. Acceptance rechecks the
recipient wallet, debits and credits atomically, and records a linked transfer.
Rejection changes no wallet. Direct and accepted-request transfers preserve the
combined-gold total.

Stage unlock proposal:

```json
{
  "request_id": "unlock-command-001",
  "proposer_id": "robot-a",
  "stage": 2,
  "contributions": { "robot-a": 20, "robot-b": 10 }
}
```

Only the next stage can be proposed, its combined-gold eligibility must be met,
and there may be only one pending unlock proposal. Contributions must include
every robot exactly once, each contribution must be a positive integer, and the
sum must equal the rule's cost. The proposer accepts automatically. No gold moves
until every robot accepts; final acceptance rechecks each wallet, deducts every
contribution in one state change, permanently advances `game.stage`, and publishes
`unlock_contribution` plus `stage_unlocked` events. Any rejection closes the
proposal without charging anyone and permits a new proposal.

Game stop cancels unfinished tasks, disables autonomous dispatch, and requests a fleet-wide motor stop. Robot stop does the equivalent for one robot. Controllers must invalidate active movement commands so their next update cannot restart motion. Resume allows new tasks; cancelled tasks never automatically resume. Game start clears a game-level pause but must not clear a separately requested robot stop. A `200` stop response confirms backend acceptance, not proof of physical motor delivery; communication loss is still covered by the onboard watchdog.

`POST /game/stop` still accepts no body for browser controls. Hardware adapters may
send `{ "session_id": "current-session-id" }` to prevent a delayed stop from
cancelling a replacement session. A mismatch returns `409 SESSION_MISMATCH`; the
check and stop execute under the same world lock. Repeating a successful stop is
idempotent. In backend-connected navigation, SPACE first latches local disarm and
requests local motor stops, then the asynchronous bridge retries this scoped game
stop. Pending acknowledgement blocks re-arming and discards queued arrivals.

### Assigning a task

```json
{
  "request_id": "request-001",
  "robot_id": "robot-a",
  "action": "SELL",
  "location": "market",
  "parameters": { "item": "wheat", "quantity": 2 }
}
```

The response uses the task shape embedded in the world example, with a new `id`, status `ASSIGNED`, progress `0`, and `error: null`. `reason` is an optional agent explanation represented as a string or `null` in responses. Frontend requests do not need to supply it.

`request_id` is required and unique per intended task within a session. Retrying the
identical request returns the same task in its current canonical state without
executing it again. Reusing the ID with different content returns `409`. The server
checks replay before checking whether the robot is busy.

| MVP action | Location | Parameters | Completion |
| --- | --- | --- | --- |
| `MOVE_TO` | Any configured location | `{}` | Confirmed arrival |
| `HARVEST` | `farm` | `plot_id` | Arrival plus backend activity timer; empties one ready plot and grants its crop |
| `FISH` | `lake` | `{}` | Arrival plus one resolved 5–15 second timer; grants one resolved fish tier |
| `BUY` | `market` | `item`, `quantity` | Arrival plus validated transaction |
| `SELL` | `market` | `item`, `quantity` | Arrival plus validated transaction |
| `PLANT` | `farm` | `item`, `plot_id` | Arrival plus validated seed consumption; creates a `GROWING` plot |
| `RETURN_HOME` | `homebase` | `{}` | Confirmed arrival |

`location` is required and validated against the action. One nonterminal task per robot; competing requests receive `409`. The game must be running and the robot available. A robot already confirmed in the required zone can skip navigation.

The shipped Market UI submits `BUY` tasks only. Autonomous agents can submit
`BUY`, `PLANT`, `HARVEST`, and `SELL` to maintain the crop loop. The mock planner
compares unlocked crops by net return per growth second and accounts for owned
seeds, pending purchases, and claimed plots before buying or planting. Successful
purchases and sales appear as transient frontend
notifications derived from authoritative world events. A task does not immediately
alter a wallet from anywhere on the map.
Check stage access, stock, prices, funds, and inventory again when the transaction
executes; apply inventory and currency changes atomically and only once. Use
execution-time prices for the MVP. A locked item returns `SEED_LOCKED`; a failed
execution fails the task without a partial transaction.

`PLANT` always consumes exactly one seed and accepts exactly `item` and `plot_id`,
for example `{ "item": "carrot_seeds", "plot_id": "plot-1" }`. The item must map
to an authoritative crop definition unlocked for the current stage. Assignment
checks that the acting robot owns the seed and the plot is empty. Arrival repeats
those checks atomically before removing the seed and setting `crop_id`,
`planted_by`, `planted_at`, `ready_at`, and status `GROWING`. If another robot
claims the plot first, execution fails with `PLOT_OCCUPIED` and keeps the seed.
Cancellation before arrival also keeps the seed.

`HARVEST` accepts exactly `{ "plot_id": "plot-1" }`. Assignment requires that the
plot exists and is `READY`. Completion repeats that check before granting the crop
and atomically returning the plot to `EMPTY`. If another robot harvests it first,
the losing task fails with `PLOT_NOT_READY` and receives no inventory. Cancellation
keeps the plot ready, and retrying the same completed request cannot grant it twice.

`FISH` accepts no parameters from clients. When the task is first assigned, the
backend resolves one duration and one catch from `world.fishing` and stores them
in the canonical task parameters:

```json
{
  "duration_seconds": 7.314,
  "catch": {
    "item_id": "uncommon_fish",
    "item_name": "Uncommon Fish",
    "sell_price": 5,
    "tier": "uncommon_fish"
  }
}
```

That result is fixed before travel begins. Reconnects and identical `request_id`
retries return the same task and cannot reroll or duplicate its catch. Completion
adds one tier-specific inventory item and publishes `fish_caught`. Set
`FISHING_RANDOM_SEED` to an integer for a repeatable sequence; simulation defaults
to seed `0`, while hardware uses system randomness when the setting is absent.

Task lifecycle:

```text
ASSIGNED → NAVIGATING → ACTIVE → COMPLETED
```

Navigation may be skipped when already at the destination. Movement-only tasks and
arrival-time transactions (`BUY`, `SELL`, and `PLANT`) complete without an activity
timer. Any nonterminal task can become `FAILED` or `CANCELLED`. `progress` measures
activity completion, not distance traveled: it stays zero during navigation,
advances during an activity, and is one on completion. Terminal failure includes
`error: { "code": "...", "message": "..." }`; otherwise error is `null`.
Cancellation or failure never grants the completion reward. Goal completion
requires both the target combined gold and Stage 3, then sets the game to
`COMPLETED`, cancels remaining work, and stops dispatch and movement.

Contract version 4 adds the authoritative `fishing` catalog and resolved fishing
task parameters to version 3's `economy`, `farm.crops`, and three shared
`farm.plots`. Empty plots
contain null crop metadata. A nonempty plot has status `GROWING` or `READY` and
must include `crop_id`, `planted_by`, `planted_at`, and `ready_at`. Clients derive
the visible queue from these records: omit empty plots, show ready plots first,
then sort growing plots by `ready_at`.

The `PLANT` action populates version 2 plots with backend timestamps. While the game
is running, the backend game loop changes each due `GROWING` plot to `READY` once
and publishes a `crop_ready` event containing `plot_id`, `crop_id`, and `ready_at`.
This continues without a connected browser and uses the same rule in simulation
and hardware modes. If the game is stopped when a timer elapses, the absolute
timestamp is preserved and the crop becomes ready on the first tick after resume.
`HARVEST` then consumes one ready plot through a backend activity timer, grants the
crop definition's `harvest_quantity` and `sell_price`, publishes `crop_harvested`,
and clears all plot crop metadata. Internal `WAIT` behavior still defers task
submission.

### Errors

All HTTP failures use:

```json
{
  "error": {
    "code": "ROBOT_BUSY",
    "message": "robot-a already has an active task."
  }
}
```

Use `400` for semantically invalid requests, `404` for unknown resources, `409`
for conflicting state or unavailable funds/stock, `422` for malformed or
schema-invalid payloads handled by FastAPI, and `503` for an unavailable required
subsystem. Examples of stable codes: `INVALID_REQUEST`, `NOT_FOUND`, `ROBOT_BUSY`,
`GAME_NOT_READY`, `GAME_NOT_RUNNING`, `ROBOT_STOPPED`, `TASK_MISMATCH`,
`INSUFFICIENT_FUNDS`, `INSUFFICIENT_INVENTORY`, `OUT_OF_STOCK`, `SEED_LOCKED`,
`PLOT_OCCUPIED`, `PLOT_NOT_READY`, and `PERSISTENCE_UNAVAILABLE`. Do not expose
secrets or stack traces in errors.

## Live updates: WebSocket /events

For the MVP, use complete snapshots rather than requiring clients to assemble state from many partial updates:

```json
{
  "type": "world_snapshot",
  "data": {
    "schema_version": 4,
    "session_id": "session-001",
    "revision": 12
  }
}
```

The abbreviated `data` above must contain the **entire canonical world object** in real messages. Send one immediately on connection, then after changes. Position/progress updates may be coalesced to a suggested 5–10 snapshots per second; this is a UI rate, not the motor-control rate. The socket is server-to-client; frontend commands use HTTP.

The frontend replaces its state with each newer snapshot, deduplicates feed events by `(session_id, event.id)`, and discards lower/equal revisions within a session. Only the current socket connection may apply updates. A different session clears old tasks, events, and revision tracking. On reconnect, the server sends current state; replay of every missed event is not required. Display disconnection and retry with bounded backoff, for example 1, 2, 4, then 5 seconds. A REST snapshot used at startup follows the same revision checks and must not overwrite newer socket state.

Suggested semantic feed types: `agent_decision`, `task_assigned`, `robot_arrived`, `task_started`, `task_completed`, `task_failed`, `task_cancelled`, `inventory_updated`, `fish_caught`, `gold_updated`, `market_updated`, `money_requested`, `money_request_accepted`, `money_request_rejected`, `money_transferred`, `stage_unlock_proposed`, `stage_unlock_accepted`, `stage_unlock_rejected`, `unlock_contribution`, `stage_unlocked`, `robot_blocked`, `robot_offline`, `tracking_stale`, `game_started`, `game_stopped`, `game_completed`. These are entries inside `world.events`, not separate required socket message formats. Unknown event types can still render their `message`.

## Robotics integration boundary

The camera adapter can share saved destinations with the hardware backend via
`HARDWARE_TRAFFIC_CONFIG` at server startup. Its `service_points` are arena pixel
coordinates converted into the existing `world.map.locations` world units; API
payloads and schema version remain unchanged. Reset preserves this configured map.
The adapter checks map agreement before following tasks. Waiting points remain
local navigation configuration and are not additional game locations. See
[camera setup](CAMERA_SETUP_GUIDE.md#named-service-and-waiting-points).

Alternatively `HARDWARE_LAYOUT=full-camera` selects normalized preset locations:
homebase (0.50,0.85), farm (0.15,0.15), lake (0.15,0.85), market (0.85,0.15),
scaled to existing world map units. It overrides HARDWARE_TRAFFIC_CONFIG in
hardware mode; navigation must use the matching full-camera preset. No payload
or schema changes are needed. This option does not certify physical clearance.

These implemented routes are for localization/navigation adapters, not browser controls.
Teammates can use equivalent in-process calls if components share a process. The
world schema and frontend routes remain unchanged.

| Caller | Method and path | Request | Success response |
| --- | --- | --- | --- |
| Localization | `POST /robots/{id}/pose` | `{ "session_id": "session-001", "pose": { "x": 42.1, "y": 63.5, "heading": 91.2 }, "timestamp": "2026-09-25T14:00:00.000Z" }` | `200`: `{ "accepted": true }` |
| Navigation | `POST /robots/{id}/arrived` | `{ "session_id": "session-001", "task_id": "task-001", "location": "farm" }` | `200`: `{ "accepted": true }` |
| Robot adapter | `POST /robots/{id}/health` | `{ "session_id": "session-001", "online": true, "battery": null, "blocked": false }` | `200`: `{ "accepted": true }` |
| Navigation | `POST /robots/{id}/blocked` | `{ "session_id": "session-001", "task_id": "task-001", "reason": "obstacle", "duration_ms": 4000 }` | `200`: `{ "accepted": true }` |

Reject reports for an old session with `409`. Ignore older/equal pose timestamps with `200` and `{ "accepted": false }`. Arrival must match the robot's active navigation task and intended location. An already accepted arrival for that task is idempotent; a cancelled or mismatched task returns `409`. Arrival starts an activity once; it does not grant a reward. The backend owns timers and task completion; there is no public endpoint that lets the frontend mark work complete.

A blocking report sets the robot's blocked state, stops the affected task from
advancing, and emits one feed event. Repeating it while the robot remains blocked
is idempotent. A deliberate health/recovery report can clear the blocked state;
fail or stop the task separately if it cannot recover. Loss of connectivity or
fresh tracking suspends task advancement. In hardware mode, the backend marks a
robot offline after `HEALTH_TIMEOUT_SECONDS` without a health heartbeat and marks
tracking `STALE` after `POSE_TIMEOUT_SECONDS` without a newer accepted pose. The
last pose remains available for display but cannot authorize navigation. Fresh
reports restore `online` and `TRACKED`. Tune these thresholds and arrival tolerance
during hardware calibration.

Backend-to-navigation command shape:

```json
{
  "session_id": "session-001",
  "task_id": "task-001",
  "robot_id": "robot-a",
  "destination": "farm",
  "target": { "x": 20, "y": 30 }
}
```

The destination is resolved by the backend/map adapter; navigation converts these normalized coordinates to calibrated physical coordinates. Carry session and task IDs through arrival, cancellation, and failure reports. Navigation must also support cancelling a task and stopping one robot or the whole fleet. A stop invalidates queued movement for cancelled tasks. Exact transport, acknowledgement, and command freshness mechanisms remain open until the robotics team selects them.

### Provisional ESP32 interface

HTTP is one possible adapter, not a required hardware transport:

| Method and robot-local path | Request | Response |
| --- | --- | --- |
| `POST /motors` | `{ "left": 0.5, "right": 0.42 }` | `{ "ok": true }` |
| `POST /stop` | none | `{ "ok": true, "left": 0, "right": 0 }` |
| `GET /status` | none | `{ "online": true, "robot_id": "robot-a" }` |

Motor values must be finite numbers in `[-1, 1]`; positive is forward, negative reverse, zero stop. Reject invalid values. The navigation controller alone calls this interface. Robot addresses, pins, protocol, control frequency, and motor calibration are hardware decisions. The `POST /robots/{id}/motors` example in `AGENTS.md` is not a required public browser API.

An ESP32-local watchdog must stop both motors after valid commands stop arriving; 500–1000 ms is an initial tuning range. Finalize watchdog timing and protection against delayed/queued commands before live operation. Network stop requests do not replace this onboard behavior.

## Agents and cooperation

Agents read authoritative state and propose the same task actions through backend validation. No specific agent SDK or decision endpoint is required. A decision includes robot ID, action, location, parameters, and a short spectator-facing reason; it never includes PWM values. Agent and manual task requests share busy-state and transaction checks.

The initial Python agent implementation lives in `backend/app/agents`. Each robot
has an independent Google ADK/Gemini agent. An in-process orchestrator supplies
world snapshots and submits the same task request fields above, plus the optional
`reason` string. Its host callback receives `session_id` separately and must apply
shared task validation and request-ID idempotency atomically. Internal `WAIT`
decisions defer submission; they do not add a public task action or endpoint.
The standalone CLI uses a temporary demo task sink, not the backend or frontend
simulation. See `backend/README.md` for environment settings and integration.

Cooperative stage and money actions use the dedicated economy routes above and do
not create movement tasks. Mock and Gemini planners submit those commands through
the same session-checked host boundary used for task assignment. Additional
physical co-op activities that require both robots at one location remain future work.

## Working without hardware

Build a simulator behind the same backend interface. It supplies pose, arrival, and health updates while real game logic handles timers, rewards, and transactions. A frontend-only mock can also serve the canonical snapshot and simulate revisions until the backend is ready. Never require a second frontend data model for hardware mode.

Suggested first demo scenario:

1. Seed two robots at home with a small wallet; game starts in `READY`.
2. Buy an unlocked seed, plant an empty plot, and wait for backend-owned readiness.
3. Harvest that ready plot while the second robot fishes.
4. Simulate changing positions and confirmed arrivals.
5. Advance backend activity progress and grant each resource once.
6. Assign sell tasks; remove inventory and increase gold.
7. Verify that the map, Crop Queue, task view, shop, wallets, and event feed agree.
8. Disconnect/reconnect the browser and confirm that the next snapshot restores current state.
9. Stop during navigation or activity and confirm that no cancelled task grants a reward.

Scripted task requests and autonomous agent decisions both exercise this scenario.
Simulation is a development tool, while the final physical demo still requires
genuine navigation and arrival.

## Implementation order and open choices

Recommended order: canonical world fixture → `GET /world` and `/events` → frontend rendering → task lifecycle with simulated motion → inventory and market → hardware adapters → autonomous decisions → cooperation. Components can be built concurrently against these contracts; this order assigns no people or ownership.

Keep these decisions open: frontend/backend frameworks, agent provider, process boundaries, robot transport, camera and marker choice, calibration and arena dimensions, game balancing, co-op mechanics beyond the repair-fund loop, optional camera feeds, deployment/authentication, and additional sponsor integrations. The current robot names are Wall-y and Eeva. Before adding any externally exposed deployment or changing shared formats, agree on the necessary contract updates together.

## Agent conversation and discussion preview

The conversation feed is separate from the canonical world WebSocket. The
frontend supplies its current snapshot for a **discussion-only** round. These
routes do not execute tasks themselves; the frontend may submit supported
proposals separately through `POST /tasks` while chat is enabled.

| Route | Purpose |
| --- | --- |
| `POST /agent-chat/round` | Body `{ "provider": "mock" or "gemini", "world": <snapshot> }`; discuss one proposed action per available robot and return chat snapshot. |
| `GET /agent-chat` | Return the current bounded conversation snapshot. |
| WebSocket `/agent-chat/events` | Send full conversation snapshots every 500 ms, including history on reconnect. |

The shipped frontend is a read-only spectator of the WebSocket feed. It does not
call `POST /agent-chat/round` or submit tasks from conversation messages.

A chat snapshot contains `session_id`, `revision`, `provider`, `mode: "discussion"`,
`running`, `error` (string or null), `interval_seconds`, and `messages`. Each message:

```json
{
  "id": "unique-message-id",
  "timestamp": "2026-09-26T18:00:00+00:00",
  "robot_id": "robot-a",
  "name": "Wall-y",
  "text": "I propose harvesting at the farm. Eeva, can you cover the lake?",
  "action": "HARVEST",
  "location": "farm",
  "parameters": { "plot_id": "plot-1" },
  "status": "proposed"
}
```

Messages are broadcasts to teammates and spectators. Sender identity comes from
the planner's assigned robot, not model-generated IDs. Gemini decisions may include
an optional `message` string (1–300 characters); it is kept out of task request
parameters. Planners receive the latest 20 messages as `agent_messages`. The
Gemini adapter also highlights the robot's recent speech, peer messages since
its last public message, and up to ten recent confirmed world events. Public
speech is optional: unchanged plans may produce no message. Near-duplicate
speech for the same robot/action/trade/status is suppressed against its six
most recent messages without suppressing task execution. Consumers must not
assume one chat message per accepted task or use chat as the task audit trail.
The in-process orchestrator also exposes `chat.snapshot()`, publishing `accepted` or
`waiting` messages after validation and task acceptance. Trade proposals carry
`{ "item": "...", "quantity": 1 }` in `parameters`; other proposals use an empty
object. The preview emits only `proposed` messages. They are not confirmations of
execution; clients must submit them through normal task validation and wait for
the authoritative world snapshot.

Backend autonomy may also publish occasional social exchanges, including while
robots are busy. These messages add `kind: "banter"` and use
`status: "conversation"`, `action: "WAIT"`, `location: null`, and empty parameters.
That WAIT is a compatibility field, not a task decision: banter never submits
tasks or alters an active task. The UI hides task labels for these messages.
After roughly 12 seconds without speech, an exchange may start; one peer reply
is scheduled four seconds after the opener, plus generation/polling latency.
Exchange starts are spaced at least 35 seconds apart. New assignments or
coordination interrupt pending banter. Stop, completion, session reset, or
unhealthy robots cancel it. Timing defaults live in `app/agents/banter.py`.
Gemini mode uses at most two extra model calls per exchange, with an eight-second
timeout per line and no tools. Mock mode uses paired scripted dialogue.

The preview has one shared room and retains 100 messages in memory. New session
IDs, provider switches, or process restarts clear history. Replace received
snapshots rather than appending them to avoid duplicates. Only one round can run
at a time (`409` otherwise); cooldown violations return `429`. Invalid request
snapshots return `422`; missing Gemini credentials return `503`. These preview
errors use FastAPI's `{ "detail": ... }` format. A model failure returns a snapshot
with `error` set and any messages already generated; the frontend pauses its loop.
The canonical game error envelope and `/events` protocol are unchanged.

The preview copies the supplied market catalog, defaults missing price fields to
null, and appends sale items from the frontend's inventory objects if absent.
This is a display/simulation adapter only; it never authorizes real transactions.

When backend autonomy is enabled, the same GET and WebSocket routes expose
accepted or waiting orchestrator messages with `mode: "autonomous"`. In that mode
the backend owns task submission and `POST /agent-chat/round` returns `409` to
prevent a competing browser planner. Starting the game remains an explicit
`POST /game/start` action. Closing every browser does not stop backend planning.
