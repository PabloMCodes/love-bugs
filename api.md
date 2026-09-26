# Game and robotics API contract

Status: active MVP contract with partial backend implementation. The authoritative
world feed, simulated `MOVE_TO`, `HARVEST`, `FISH`, `BUY`, and `SELL` tasks, and
pose, arrival, and health ingestion are implemented; remaining routes and hardware adapters
are still planned. Update this document and affected consumers together when
changing a contract.

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
  "schema_version": 1,
  "session_id": "session-001",
  "revision": 12,
  "updated_at": "2026-09-25T14:00:00.000Z",
  "mode": "simulation",
  "game": {
    "status": "RUNNING",
    "goal": { "type": "earn_gold", "target": 500, "current": 80 }
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
      "name": "Billy",
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
          "wheat": { "name": "Wheat", "quantity": 2, "sell_price": 10 },
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
        "parameters": {},
        "reason": "Harvest wheat to sell at the market.",
        "error": null
      }
    },
    {
      "id": "robot-b",
      "name": "Milo",
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
      { "id": "seeds", "name": "Wheat Seeds", "buy_price": 5, "sell_price": null, "stock": null },
      { "id": "tool_upgrade", "name": "Tool Upgrade", "buy_price": 40, "sell_price": null, "stock": 1 }
    ]
  },
  "events": [
    {
      "id": "event-001",
      "timestamp": "2026-09-25T13:59:58.000Z",
      "type": "task_started",
      "robot_id": "robot-a",
      "task_id": "task-001",
      "message": "Billy started harvesting wheat.",
      "data": {}
    }
  ]
}
```

- `mode`: `simulation` or `hardware`. Simulation must be visibly identifiable in the UI.
- `game.status`: `READY`, `RUNNING`, `STOPPED`, or `COMPLETED`.
- `revision`: increases on each published state change within a session. Reset creates a new `session_id` and restarts revision numbering.
- Every endpoint returning a robot uses the canonical robot shape above. `task` is the current nonterminal task or `null`; terminal tasks remain available in task history.
- `physical.online` describes robot communication; `tracking` independently describes localization: `TRACKED`, `STALE`, or `UNKNOWN`. Initially pose and pose timestamp are `null`, and tracking is `UNKNOWN`. A stale pose may remain for display but must not be treated as fresh control input. The hardware adapter defines and documents its freshness threshold before live driving.
- `battery` is a fraction from 0 to 1 or `null`. `stopped` is a latched control stop, not an indication that the wheels happen to be stationary.
- The market list contains items available to buy. Inventory entries contain their execution-time `sell_price`; `null` means that item cannot be sold. `stock: null` means unlimited shop stock; zero means sold out. MVP inventory has no capacity limit.
- `events` contains the latest 100 semantic events, oldest first. Pose samples are not feed events. Event `robot_id` and `task_id` may be `null`. `data` contains optional details; the UI can always display `message`.

## Frontend-facing HTTP API

Routes below are the proposed MVP surface. Empty request bodies are shown as “none.” All writes return after server acceptance or state mutation; acceptance does not mean physical completion.

| Method and path | Request | Success response |
| --- | --- | --- |
| `GET /world` | none | `200`: canonical world snapshot |
| `GET /robots` | none | `200`: `{ "robots": [...] }`, canonical robots |
| `GET /robots/{id}` | none | `200`: canonical robot |
| `GET /market` | none | `200`: canonical market object |
| `POST /goal` | `{ "type": "earn_gold", "target": 500 }` | `200`: updated goal object; allowed only in `READY` |
| `POST /game/start` | none | `200`: world snapshot; starts from `READY`, resumes from `STOPPED` |
| `POST /game/stop` | none | `200`: world snapshot after stop is latched |
| `POST /game/reset` | none | `200`: new session snapshot in `READY` |
| `POST /robots/{id}/stop` | none | `200`: canonical robot after stop is latched |
| `POST /robots/{id}/resume` | none | `200`: canonical robot with stop latch cleared; requires a running game and healthy robot |
| `POST /tasks` | task request below | `202`: canonical task in `ASSIGNED` |
| `GET /tasks` | none | `200`: `{ "tasks": [...] }`, all tasks in current session, creation order |
| `GET /tasks/{id}` | none | `200`: canonical task, including terminal results |

Repeated start while running and repeated stops succeed without repeating side effects. Starting a completed game returns `409`; reset first. Reset cancels work and stops the fleet before clearing game state. In hardware mode it does not teleport robots or assert that they are at home; preserve actual telemetry and await fresh localization. In simulation, reset may place them at home.

Game stop cancels unfinished tasks, disables autonomous dispatch, and requests a fleet-wide motor stop. Robot stop does the equivalent for one robot. Controllers must invalidate active movement commands so their next update cannot restart motion. Resume allows new tasks; cancelled tasks never automatically resume. Game start clears a game-level pause but must not clear a separately requested robot stop. A `200` stop response confirms backend acceptance, not proof of physical motor delivery; communication loss is still covered by the onboard watchdog.

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

`request_id` is required and unique per intended task within a session. Retrying the identical request returns the original task without executing it again. Reusing the ID with different content returns `409`. The server checks replay before checking whether the robot is busy.

| MVP action | Location | Parameters | Completion |
| --- | --- | --- | --- |
| `MOVE_TO` | Any configured location | `{}` | Confirmed arrival |
| `HARVEST` | `farm` | `{}` | Arrival plus backend activity timer; adds crop |
| `FISH` | `lake` | `{}` | Arrival plus backend activity timer; adds fish |
| `BUY` | `market` | `item`, `quantity` | Arrival plus validated transaction |
| `SELL` | `market` | `item`, `quantity` | Arrival plus validated transaction |
| `RETURN_HOME` | `homebase` | `{}` | Confirmed arrival |

`location` is required and validated against the action. One nonterminal task per robot; competing requests receive `409`. The game must be running and the robot available. A robot already confirmed in the required zone can skip navigation.

Shop buttons submit `BUY`/`SELL` tasks for the selected robot. They do not immediately alter its wallet from anywhere on the map. Check stock, prices, funds, and inventory again when the transaction executes; apply inventory and currency changes atomically and only once. Use execution-time prices for the MVP and explain this in the shop UI. A failed validation fails the task without a partial transaction.

Task lifecycle:

```text
ASSIGNED → NAVIGATING → ACTIVE → COMPLETED
```

Navigation may be skipped when already at the destination. Movement-only tasks complete on arrival without an activity timer. Any nonterminal task can become `FAILED` or `CANCELLED`. `progress` measures activity completion, not distance traveled: it stays zero during navigation, advances during an activity, and is one on completion. Terminal failure includes `error: { "code": "...", "message": "..." }`; otherwise error is `null`. Cancellation or failure never grants the completion reward. Goal completion sets the game to `COMPLETED`, cancels remaining work, and stops dispatch and movement.

Planting, growth cycles, upgrades, and `WAIT` need not be implemented to support this contract. Initially `HARVEST` can mean a simple timed collection without seed consumption. Any agent waiting behavior can simply defer task submission.

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

Use `400` for invalid JSON/fields/actions, `404` for unknown resources, `409` for conflicting state or unavailable funds/stock, and `503` for an unavailable required subsystem. Examples of stable codes: `INVALID_REQUEST`, `NOT_FOUND`, `ROBOT_BUSY`, `GAME_NOT_RUNNING`, `ROBOT_STOPPED`, `TASK_MISMATCH`, `INSUFFICIENT_FUNDS`, `INSUFFICIENT_INVENTORY`, `OUT_OF_STOCK`, `SUBSYSTEM_UNAVAILABLE`. Do not expose secrets or stack traces in errors.

## Live updates: WebSocket /events

For the MVP, use complete snapshots rather than requiring clients to assemble state from many partial updates:

```json
{
  "type": "world_snapshot",
  "data": {
    "schema_version": 1,
    "session_id": "session-001",
    "revision": 12
  }
}
```

The abbreviated `data` above must contain the **entire canonical world object** in real messages. Send one immediately on connection, then after changes. Position/progress updates may be coalesced to a suggested 5–10 snapshots per second; this is a UI rate, not the motor-control rate. The socket is server-to-client; frontend commands use HTTP.

The frontend replaces its state with each newer snapshot, deduplicates feed events by `(session_id, event.id)`, and discards lower/equal revisions within a session. Only the current socket connection may apply updates. A different session clears old tasks, events, and revision tracking. On reconnect, the server sends current state; replay of every missed event is not required. Display disconnection and retry with bounded backoff, for example 1, 2, 4, then 5 seconds. A REST snapshot used at startup follows the same revision checks and must not overwrite newer socket state.

Suggested semantic feed types: `agent_decision`, `task_assigned`, `robot_arrived`, `task_started`, `task_completed`, `task_failed`, `task_cancelled`, `inventory_updated`, `gold_updated`, `market_updated`, `help_requested`, `help_accepted`, `robot_blocked`, `game_started`, `game_stopped`, `game_completed`. These are entries inside `world.events`, not separate required socket message formats. Unknown event types can still render their `message`.

## Robotics integration boundary

These routes are for localization/navigation adapters, not browser controls. The
pose, arrival, and health routes are implemented; the blocked row is a proposed adapter interface.
Teammates can use equivalent in-process calls if components share a process. The
world schema and frontend routes remain unchanged.

| Caller | Method and path | Request | Success response |
| --- | --- | --- | --- |
| Localization | `POST /robots/{id}/pose` | `{ "session_id": "session-001", "pose": { "x": 42.1, "y": 63.5, "heading": 91.2 }, "timestamp": "2026-09-25T14:00:00.000Z" }` | `200`: `{ "accepted": true }` |
| Navigation | `POST /robots/{id}/arrived` | `{ "session_id": "session-001", "task_id": "task-001", "location": "farm" }` | `200`: `{ "accepted": true }` |
| Robot adapter | `POST /robots/{id}/health` | `{ "session_id": "session-001", "online": true, "battery": null, "blocked": false }` | `200`: `{ "accepted": true }` |
| Navigation | `POST /robots/{id}/blocked` | `{ "session_id": "session-001", "task_id": "task-001", "reason": "obstacle", "duration_ms": 4000 }` | `200`: `{ "accepted": true }` |

Reject reports for an old session with `409`. Ignore older/equal pose timestamps with `200` and `{ "accepted": false }`. Arrival must match the robot's active navigation task and intended location. An already accepted arrival for that task is idempotent; a cancelled or mismatched task returns `409`. Arrival starts an activity once; it does not grant a reward. The backend owns timers and task completion; there is no public endpoint that lets the frontend mark work complete.

A blocking report stops the affected motion and emits a feed event. Recovery policy can be chosen by the navigation team; resume only through a deliberate recovery decision, and fail the task if it cannot recover. Loss of connectivity or fresh tracking must suspend live driving. Hardware thresholds and arrival tolerance are configuration to agree on during calibration.

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

Cooperation is the next integration milestone after the individual gameplay loop. Reserve `help_requested` and `help_accepted` feed events, but do not require a speculative co-op API to unblock the frontend. Before implementing cooperation, agree on a shared objective ID, participant list, invitation/acceptance flow, waiting/active/completed/cancelled states, reward split, and timeout/cancellation behavior. Both robots must have confirmed arrival before the shared activity starts, and its reward must be applied once. The exact objective and agent communication mechanism remain open.

## Working without hardware

Build a simulator behind the same backend interface. It supplies pose, arrival, and health updates while real game logic handles timers, rewards, and transactions. A frontend-only mock can also serve the canonical snapshot and simulate revisions until the backend is ready. Never require a second frontend data model for hardware mode.

Suggested first demo scenario:

1. Seed two robots at home with a small wallet; game starts in `READY`.
2. Start the game and assign robot A to harvest and robot B to fish.
3. Simulate changing positions and confirmed arrivals.
4. Advance backend activity progress, complete tasks, and grant resources once.
5. Assign a sell task; travel to market, remove inventory, and increase gold.
6. Verify that the map, task view, shop, wallets, and event feed agree.
7. Disconnect/reconnect the browser and confirm that the next snapshot restores current state.
8. Stop during navigation and confirm that no activity or reward occurs for the cancelled task.

Initially scripted task requests can exercise this scenario; autonomous agent decisions replace those requests later. Simulation is a development tool, while the final physical demo still requires genuine navigation and arrival.

## Implementation order and open choices

Recommended order: canonical world fixture → `GET /world` and `/events` → frontend rendering → task lifecycle with simulated motion → inventory and market → hardware adapters → autonomous decisions → cooperation. Components can be built concurrently against these contracts; this order assigns no people or ownership.

Keep these decisions open: frontend/backend frameworks, agent provider, process boundaries, robot transport, camera and marker choice, calibration and arena dimensions, actual names/artwork, game balancing, co-op mechanics, optional camera feeds, deployment/authentication, and additional sponsor integrations. Before adding any externally exposed deployment or changing shared formats, agree on the necessary contract updates together.

## Agent conversation preview

The local chat preview is separate from the canonical world WebSocket. The
frontend supplies its current snapshot for a **discussion-only** round. These
routes do not execute tasks themselves; the frontend may submit supported
proposals separately through `POST /tasks` while chat is enabled.

| Route | Purpose |
| --- | --- |
| `POST /agent-chat/round` | Body `{ "provider": "mock" or "gemini", "world": <snapshot> }`; discuss one proposed action per available robot and return chat snapshot. |
| `GET /agent-chat` | Return the current bounded conversation snapshot. |
| WebSocket `/agent-chat/events` | Send full conversation snapshots every 500 ms, including history on reconnect. |

A chat snapshot contains `session_id`, `revision`, `provider`, `mode: "discussion"`,
`running`, `error` (string or null), `interval_seconds`, and `messages`. Each message:

```json
{
  "id": "unique-message-id",
  "timestamp": "2026-09-26T18:00:00+00:00",
  "robot_id": "robot-a",
  "name": "Billy",
  "text": "I propose harvesting at the farm. Milo, can you cover the lake?",
  "action": "HARVEST",
  "location": "farm",
  "parameters": {},
  "status": "proposed"
}
```

Messages are broadcasts to teammates and spectators. Sender identity comes from
the planner's assigned robot, not model-generated IDs. Gemini decisions may include
an optional `message` string (1–300 characters); it is kept out of task request
parameters. Planners receive the latest 20 messages as `agent_messages`. The
in-process orchestrator also exposes `chat.snapshot()`, publishing `accepted` or
`waiting` messages after validation and task acceptance. Trade proposals carry
`{ "item": "...", "quantity": 1 }` in `parameters`; other proposals use an empty
object. The preview emits only `proposed` messages. They are not confirmations of
execution; clients must submit them through normal task validation and wait for
the authoritative world snapshot.

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
