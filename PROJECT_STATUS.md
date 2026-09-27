# Love Bugs project status and teammate handoff

Last updated: **September 27, 2026**

Working branch: **`gameLogic`**

Canonical world schema: **version 4**

Current product milestone: **complete autonomous simulation; physical demo integration and presentation polish remain**

## Purpose of this document

This is the consolidated project handoff for teammates and coding agents. It
answers four questions:

1. What is Love Bugs supposed to be?
2. What has actually been implemented?
3. What contracts must other subsystems preserve?
4. What work is still required for a complete demo?

This file summarizes the repository rather than replacing its specialized
documentation. When details disagree, use the following order of authority:

1. [`api.md`](api.md) for HTTP, WebSocket, schema, and lifecycle contracts.
2. [`GAME_DESIGN.md`](GAME_DESIGN.md) for current gameplay rules and design intent.
3. [`GAME_PLAN.md`](GAME_PLAN.md) for milestones, priorities, and acceptance flow.
4. [`INTEGRATION.md`](INTEGRATION.md) for subsystem handoff procedures.
5. [`backend/README.md`](backend/README.md),
   [`frontend/README.md`](frontend/README.md), and
   [`backend/app/navigation/README.md`](backend/app/navigation/README.md) for
   subsystem setup and operation.

## Executive summary

Love Bugs is a cooperative robot farming game starring **Wall-y** and **Eeva**.
The robots independently choose high-level work, travel through a shared world,
farm or fish for resources, sell their own inventory, help one another with
money, cooperatively unlock later farming stages, and work toward a shared gold
goal.

The project deliberately separates decisions from motion:

- Mock or Gemini agents choose bounded high-level actions.
- The backend validates and owns every task, timer, item, wallet change, stage
  unlock, and victory transition.
- Simulation or the physical navigation adapter supplies movement and arrival.
- The frontend observes authoritative backend state and presents the game.
- SQLite or Tiger Data persists accepted state, events, and position history.

The game is currently playable end to end in **simulation mode without physical
robots and without keeping a browser open**. The complete simulated loop includes
seed purchasing, planting, timed growth, plot-aware harvesting, tiered fishing,
selling, money requests, cooperative stage unlocks, and victory.

The demo rules and physical service points are now startup configuration rather
than source edits. `backend/game_config.json` defines the committed profile, and
`GAME_CONFIG_PATH` selects a validated replacement. The deterministic seed-0
mock round measures approximately 88 simulated seconds at the production
movement rate; an automated 60–120 second regression test protects that window.

The physical stack is substantially implemented: overhead ArUco localization,
two independent BLE robot profiles, calibrated boundaries and building
obstacles, traffic reservation, detour planning, backend task consumption,
telemetry publishing, arrival reporting, and an optional command-expiry firmware
variant all exist. It is not yet correct to call the physical demo complete.
Real camera calibration, robot-specific heading/turn calibration, watchdog
firmware flashing, and a full two-robot acceptance run are still required.

## Current project status at a glance

Status meanings:

- **Implemented:** exists in code and has automated coverage.
- **Partial:** useful implementation exists, but the intended user-facing or
  physical acceptance result is incomplete.
- **Pending:** planned but not yet implemented or verified.

| Area | Status | Current result |
| --- | --- | --- |
| Canonical backend world | Implemented | Thread-safe schema-version-4 snapshots with revisions, sessions, semantic events, robots, farm, fishing, market, and economy state. |
| Game lifecycle | Implemented | Start, stop, reset, configurable goal, robot stop/resume, completion, and cancellation rules. |
| Simulation | Implemented | Movement, arrival, telemetry, activities, trading, farming, autonomy, and a full no-browser round. |
| Farming | Implemented | Three crops, three default shared plots, configurable plot capacity, seed consumption, growth timers, readiness, plot-aware harvest, and exact-once rewards. |
| Fishing | Implemented | Seedable 5–15 second attempts and three weighted reward tiers fixed once per task. |
| Market | Implemented | Stage-locked seed purchases and inventory-based sales with execution-time validation. |
| Cooperative economy | Implemented | Paid stage proposals, two-robot approval, contributions, direct transfers, money requests, retry safety, and timeout recovery. |
| Agent autonomy | Implemented | Deterministic mock planner and Gemini planner share the same bounded decision/validation contract. |
| Spectator conversation | Implemented | Accepted/waiting decisions, coordination messages, occasional banter, traffic messages, WebSocket updates, and auto-scrolling UI. |
| Frontend dashboard | Implemented | Robot tracker, hardware-input readiness, game/economy status, market, crop queue, null-safe world map, transaction notices, and conversation layout. |
| Victory presentation | Implemented | `COMPLETED` state opens a dedicated celebration with authoritative team totals and reset control. |
| Economy presentation | Implemented | Pending votes/requests, completed contributions, recent transfers, and funded-upgrade count are visible in game status. |
| Map stage presentation | Partial | World state exposes the stage and crops; crop-specific farm/map artwork still needs to react to progression. |
| Persistence | Implemented | SQLite default, Tiger/Timescale support, migrations, setup/check CLI, rollback, history, and restart behavior. |
| Vision/localization | Implemented in software | ArUco detection, coordinate calibration, zones, timestamps, and pose ingestion exist; final arena calibration remains physical work. |
| Navigation and traffic | Implemented in software | Two-robot BLE control, safety latches, boundaries, static obstacles, detours, backend bridge, and arrival reporting exist. |
| Physical robot demo | Pending verification | Requires calibration, watchdog flashing, live telemetry, and the complete hardware acceptance run. |
| Balance and pacing | Implemented for deterministic simulation | The committed seed-0 profile completes in about 88 simulated seconds; real-robot travel pacing still requires measurement. |

## Product goal and intended player experience

The first complete scenario is **The Repair Fund**:

1. Wall-y and Eeva start at `homebase` with separate wallets and empty
   inventories.
2. The game enters `RUNNING`, enabling backend-owned autonomy.
3. Robots choose complementary farming or fishing work.
4. Farming requires buying a seed, planting it in a specific empty plot,
   waiting for backend-owned growth, harvesting that ready plot, and carrying
   the crop to market.
5. Fishing offers a lower predictable expected rate with variable timing and
   rewards.
6. Sales credit only the robot that owns and sells the item.
7. The shared goal is the sum of both current wallet balances.
8. Stage 2 and Stage 3 require eligibility, an explicit proposal, approval from
   both robots, and affordable positive contributions.
9. Robots can request or transfer money for a concrete purchase or unlock plan.
10. The game completes only after Stage 3 is active and combined wallet gold
    reaches the configured target.
11. Completion cancels remaining work and prevents new dispatch.

The spectator should be able to understand what each robot is doing, why it made
that choice, how its personal inventory and wallet changed, how cooperation
advanced the stage, and when the team won.

## Current authoritative gameplay values

These are implemented defaults, not promises that balancing is finished.

### Initial world

| Setting | Current value |
| --- | --- |
| Robots | `robot-a` / Wall-y and `robot-b` / Eeva |
| Starting location | `homebase` |
| Starting wallet | 40 gold per robot; 80 combined |
| Starting inventory | Empty |
| Starting farm stage | Stage 1 |
| Final goal | 200 combined wallet gold after Stage 3 is active |
| Farm capacity | Three shared plots |
| World coordinates | 100 × 100 normalized UI/world space |
| Locations | `homebase` (50,30), `farm` (20,50), `lake` (12,30), `market` (80,25) |

### Crop economy

| Stage | Seed/item IDs | Seed cost | Growth | Harvest | Gross sale | Net after seed |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `seeds` → `wheat` | 5 | 8 s | 3 × 12 | 36 | 31 |
| 2 | `carrot_seeds` → `carrot` | 10 | 12 s | 3 × 20 | 60 | 50 |
| 3 | `pumpkin_seeds` → `pumpkin` | 20 | 18 s | 3 × 32 | 96 | 76 |

All unlocked seeds remain visible in the current market. Purchases are blocked
until `game.stage` meets the item's `required_stage`. The backend—not the UI or
agent—revalidates stage, funds, stock, inventory, plot state, and prices when the
action executes.

### Stage progression

| Unlock | Eligibility | Paid cost | Current rule |
| --- | ---: | ---: | --- |
| Stage 2 / Carrots | 100 combined gold | 30 total gold | Both robots accept explicit positive contributions. |
| Stage 3 / Pumpkins | 150 combined gold | 60 total gold | Both robots accept explicit positive contributions. |

Eligibility alone never changes the stage. Contributions are atomically checked
and deducted only after all required approvals. Retries cannot pay twice.

### Fishing economy

Each `FISH` task receives one duration from 5–15 seconds and one catch tier when
the task is first accepted:

| Item ID | Display name | Probability | Sale value |
| --- | --- | ---: | ---: |
| `common_fish` | Common Fish | 70% | 1 gold |
| `uncommon_fish` | Uncommon Fish | 25% | 5 gold |
| `rare_fish` | Extremely Rare Fish | 5% | 15 gold |

The current expected value is 2.7 gold per attempt. At the mean duration of 10
seconds, that is 0.27 expected gold per second before travel time. Simulation
defaults to random seed `0` for reproducible demos. Hardware uses system
randomness unless `FISHING_RANDOM_SEED` is explicitly configured.

The resolved duration and catch are stored in canonical task parameters before
travel begins. A reconnect, persistence restart, repeated request ID, or delayed
arrival cannot reroll the result. Cancellation grants no catch; completion grants
the catch exactly once.

## Architecture and ownership

```text
Mock/Gemini agents ──high-level decision──┐
Frontend commands ─────HTTP───────────────┤
Localization/robot reports ──HTTP─────────┤
                                          ▼
                              FastAPI + WorldStore
                         validation / tasks / economy
                              timers / exact-once effects
                                  │           │
                    full snapshots│           │atomic records
                                  ▼           ▼
                         Frontend/WebSocket   SQLite or Tiger
                                  ▲
                                  │ pose + arrival
                    Simulation or hardware navigation bridge
                                  │
                                  ▼
                           ESP32/BLE motor control
```

Subsystem boundaries:

| Subsystem | Owns | Must not own |
| --- | --- | --- |
| Frontend | Rendering, session controls, market purchase interaction, reconnection, local offline fallback | Authoritative timers, rewards, wallet math, stage changes, or physical motion |
| Backend/game | World state, validation, task lifecycle, inventory, wallets, market, plots, fishing, stages, victory | Camera capture details or direct UI rendering |
| Agents | Choosing among allowed high-level actions and explaining decisions | Motor commands, direct state mutation, invented success, or reward calculation |
| Simulation | Development movement, generated telemetry, and arrival | Different gameplay rules from hardware mode |
| Vision/localization | Marker-to-pose conversion and fresh observations | Granting rewards or declaring game actions complete |
| Navigation/control | Safe destination following, local traffic control, arrival/blockage reports | Deciding game rewards or bypassing backend tasks |
| ESP32 firmware | Executing motor commands and stopping on invalid/stale control | Business/game decisions |
| Persistence | Atomic durable snapshots, events, positions, and idempotency records | Alternate gameplay state or direct client writes |

## Work completed so far

### 1. Repository and contract foundation

- Added collaborative workflow rules to protect teammate changes and prohibit
  force pushes, secret commits, and unsafe resets.
- Defined the stable MVP application contract before implementing integrations.
- Separated frontend, backend/API, agents, game rules, simulation, persistence,
  vision, navigation, robot communication, and firmware responsibilities.
- Standardized stable robot IDs (`robot-a`, `robot-b`) separately from display
  names (Wall-y, Eeva).
- Established session IDs, monotonically increasing revisions, semantic events,
  request IDs, and full world snapshots as integration primitives.

### 2. Authoritative backend and API

- Built a FastAPI backend with Pydantic validation and a thread-safe
  `WorldStore`.
- Added `GET /world`, focused robot/market/economy/task queries, lifecycle
  commands, goal configuration, task assignment, economy commands, telemetry
  ingestion, history queries, and WebSocket world snapshots.
- Added retry-safe request IDs. Repeating the same request returns the canonical
  result; reusing an ID with different content returns a conflict.
- Added atomic publish/rollback behavior so a persistence failure cannot leave an
  unrecorded in-memory transition visible.
- Added bounded semantic event history and task history after tasks leave the
  robot's active task field.
- Advanced the canonical world from the original mock model through farm and
  economy additions to schema version 4 with authoritative fishing rules.
- Added a strict external game profile for service points, starting economy,
  goal, plots, crops, market items, unlocks, and fishing. Invalid or inconsistent
  profiles fail before the server starts.

### 3. Task lifecycle, simulation, and safety

- Implemented `MOVE_TO`, `RETURN_HOME`, `BUY`, `SELL`, `PLANT`, `HARVEST`, and
  `FISH` tasks.
- Implemented lifecycle transitions through `ASSIGNED`, `NAVIGATING`, `ACTIVE`,
  and terminal `COMPLETED`, `FAILED`, or `CANCELLED` states.
- Added a backend movement simulator so the same tasks can complete without
  physical robots.
- Added arrival confirmation and blocked reporting for real navigation.
- Added global game start/stop/reset and per-robot stop/resume controls.
- Added health and pose freshness watchdogs. Offline, blocked, stopped, stale,
  untracked, or unknown-pose robots cannot continue unsafe work.
- Made goal completion cancel remaining work and stop later dispatch.
- Added a hardware-mode contract test that drives two robot telemetry, both
  cooperative unlocks, buy, plant, timed growth, harvest, sale, and victory only
  through authoritative API inputs, including duplicate-arrival protection.
- Added a bridge transport test proving a queued physical arrival reaches the
  real backend route and executes its game effect exactly once.

### 4. Market and per-robot ownership

- Replaced shared/ambiguous inventory behavior with separate robot wallets and
  inventories.
- Added backend-authoritative purchasing and selling at the market.
- Fixed agent sale validation to use the selected robot's own inventory.
- Replaced the early generic store idea with Wheat, Carrot, and Pumpkin seeds.
- Added stage locks for later seeds and clear locked-stage market presentation.
- Converted the market UI to purchase-only interaction; autonomous sales remain
  visible as parchment notifications instead of a manual sell tab.
- Added compact purchase and sale notifications with distinct green/gold text.

### 5. Farming and Crop Queue

- Added three authoritative shared farm plots.
- Added crop definitions for Wheat, Carrots, and Pumpkins.
- Implemented `PLANT` with exact seed consumption and explicit `plot_id`.
- Added backend timestamps for `planted_at` and `ready_at`.
- Added backend-owned `GROWING` → `READY` transitions and `crop_ready` events.
- Made `HARVEST` require a specific ready plot and revalidate it at completion.
- Made harvest grant the configured crop exactly once and clear the plot.
- Prevented two robots from claiming the same plot or receiving duplicate
  harvest rewards.
- Built the left-side Crop Queue from canonical farm plots. It hides empty plots,
  orders ready crops first, and displays timestamp-derived growth progress.
- Taught planners to avoid excess seed purchases, reserve distinct plots, plant
  owned seeds, harvest ready plots, and sell completed crops.

### 6. Cooperative progression and money

- Replaced automatic threshold unlocks with explicit paid cooperative unlocks.
- Added proposal creation, accept/reject responses, positive per-robot
  contributions, atomic deduction, and permanent stage advancement.
- Added direct money transfers and request/accept/reject money workflows.
- Ensured transfers conserve total gold and retries cannot move money twice.
- Required Stage 3 as well as final target gold for victory.
- Taught mock and Gemini autonomy to reason about unlocks and pending economy
  work.
- Added exact-shortfall money requests for a profitable seed purchase that the
  requesting robot cannot afford alone.
- Added configurable expiration for unanswered money requests and stage
  proposals. Expiration charges nothing, emits a semantic event, rejects late
  responses, and lets autonomy submit a replacement instead of waiting forever.

### 7. Strategic tiered fishing

- Replaced the original fixed-duration, fixed-value Salmon placeholder with the
  three-tier fishing catalog shown above.
- Added injectable randomness and repeatable simulation/test seeds.
- Resolve duration and reward at assignment rather than completion to protect
  retry and persistence semantics.
- Added tier-specific inventory entries and `fish_caught` events.
- Updated the browser's local fallback to use the same catalog shape and emit the
  same outcome type.
- Taught the mock planner to compare crop net return per growth second with
  fishing's expected gold per second.
- Taught it to skip an unaffordable crop when neither wallet can fund the
  shortfall and choose the next feasible profitable crop before fishing.
- Added the fishing rules to Gemini's snapshot and prompt while keeping the
  backend authoritative for the actual random outcome.

### 8. Backend-owned autonomy and conversation

- Added an independent Google ADK `LlmAgent`/runner per robot.
- Added a deterministic mock planner for offline development and reliable demos.
- Moved recurring autonomy into the backend so gameplay continues without an
  open browser.
- Kept all decisions inside one validated action schema and submitted them
  through the same task/economy services as other clients.
- Scheduled robots sequentially so the second planner sees the first robot's
  accepted decision and can avoid duplicate work.
- Added timeout/error isolation and reconciliation for uncertain submissions.
- Removed frontend ownership of voice/start-chat planning controls; the
  conversation panel is a read-only spectator view.
- Added grounded coordination messages, suppression of repetitive chatter, and
  occasional paired banter while idle.
- Added deterministic traffic conversation from the navigation controller
  without allowing an LLM to make motor-safety decisions.

### 9. Frontend dashboard and visual work

- Connected the React/Vite/Tailwind frontend to `GET /world` and WebSocket
  `/events`, with revision/session protection against stale updates.
- Retained a local simulation fallback when the backend is unavailable.
- Built the Robot Tracker with task, inventory, money, location, status, and
  progress per robot.
- Added the centered **Love Bugs <3** header and consistent white/navy outlined
  section titles.
- Added the Farm Stage header above the progress panel and removed the old Repair
  Fund copy from that component.
- Positioned Crop Queue on the far left, the main tracker/status/market/map in
  the center, and Robot Conversation on the far right.
- Expanded the World Map into the space previously occupied by conversation.
- Added rounded Market, World Map, and Robot Conversation panels.
- Added pixel-art styling and existing Paper/cloud/chat/ladybug assets.
- Added smooth conversation auto-scroll that pauses when a user scrolls away
  from the bottom.
- Fixed market overflow/padding and made locked-stage badges match the pixel
  button style.
- Made hardware startup safe when robot poses are still unknown instead of
  dereferencing null localization data on the map.
- Added explicit offline, stale tracking, awaiting-pose, blocked, stopped, and
  all-input-ready presentation; hardware start stays disabled until both robots
  have usable input.
- Added a compact cooperative economy status for pending votes/requests, recent
  contributions/transfers, and funded upgrade count.
- Added an authoritative victory overlay driven only by `game.status ===
  "COMPLETED"`, with team totals and a backend reset action.

### 10. Persistence and database setup

- Added local SQLite persistence as the zero-configuration default.
- Added PostgreSQL/Tiger Data support with TimescaleDB 2.13+ requirements.
- Persisted the latest world snapshot per session, semantic events, position
  samples, duplicate-event protection, and deterministic event ordering.
- Added history APIs for events and robot positions across sessions.
- Added migrations, transaction rollback coverage, restart/history coverage,
  and session-safe event identity.
- Added `python -m app.persistence init` for idempotent setup/migration and
  `python -m app.persistence check` for read-only verification.
- Added explicit `--env-file` support without automatically discovering or
  committing local credentials.
- Added isolated live Tiger verification when `TEST_DATABASE_URL` is supplied.
- Verified that real economy effects—including selling a dynamically resolved
  fish—survive persistence and request retries.

### 11. Vision, BLE navigation, and traffic safety

- Added standalone overhead ArUco localization with generated-frame tests.
- Added phased click-to-drive bring-up: localization, geometry, dry run, and
  pulsed BLE movement.
- Added independent Wall-y and Eeva profiles with unique markers and BLE names.
- Added mandatory two-robot fleet traffic protection for phase-4 motion.
- Added saved arena boundaries, complete-robot radii, safety margin, static
  building obstacles, stopping-clearance prediction, detour search, alternating
  priority, and settling delay.
- Added a camera-based calibration editor for arena, buildings, robot footprint,
  and marker center.
- Made unreviewed/missing calibration, resolution changes, stale camera data,
  missing markers, BLE failures, and route failures stop motion.
- Added a hardware backend bridge that consumes assigned tasks, publishes pose
  and health, reports blocked state, and confirms matching arrivals.
- Kept inventory, coins, task effects, and activity timers in the backend rather
  than the navigation process.

### 12. Firmware and physical assets

- Preserved the original WALL-Y firmware under `firmware/wall_y/`.
- Added an optional watchdog firmware variant that stops after 500 ms without a
  valid motion refresh, as well as on stop, disconnect, and boot.
- Added CAD/3D-print project artifacts and public visual assets used by the demo.
- Physical compilation, flashing, motor-pin verification, and full arena testing
  remain hands-on tasks.

### Reported physical verification evidence

The team has reported successful iPhone/Continuity Camera input and control of
both robots during an earlier phase-4 bring-up. That run does not count as the
final guarded demo: one log came from older code with traffic protection disabled,
and a later protected run correctly issued only STOP commands because the saved
traffic configuration still had `calibrated: false`. There is not yet recorded
evidence of both robots completing guarded routes around the configured buildings
and then completing game tasks, rewards, and sales.

Treat this distinction carefully:

- Camera and BLE feasibility have been demonstrated by the team.
- Traffic/navigation behavior has strong automated coverage.
- The physical calibration editor and guarded bridge exist.
- A complete guarded physical game round is still pending.
- The watchdog firmware variant exists but has not been confirmed flashed and
  tested on both robots.
- Live Tiger Data success is not claimed without a locally supplied connection
  and an unskipped integration test.

## Canonical application contract

### World snapshot

Every authoritative snapshot contains:

- `schema_version`, `session_id`, `revision`, `updated_at`, and runtime `mode`.
- `game`: lifecycle status, combined-gold goal, and permanent farm stage.
- `map`: normalized dimensions and named destinations.
- `robots`: physical state, game location, individual wallet/inventory, and one
  current nonterminal task or `null`.
- `market`: visible seed definitions and stage requirements.
- `farm`: crop definitions and three plot records.
- `fishing`: duration bounds and weighted tier definitions.
- `economy`: unlock rules/proposals, money requests, and transfers.
- `events`: the newest 100 semantic events in chronological order.

The frontend must replace its state only with a newer revision in the same
session. A new session clears session-local event/task/revision tracking.

### Public task actions

| Action | Destination | Client parameters | Completion behavior |
| --- | --- | --- | --- |
| `MOVE_TO` | Any named location | `{}` | Completes on confirmed arrival. |
| `RETURN_HOME` | `homebase` | `{}` | Completes on confirmed arrival. |
| `BUY` | `market` | `item`, `quantity` | Revalidates and completes on arrival. |
| `SELL` | `market` | `item`, `quantity` | Revalidates seller inventory and completes on arrival. |
| `PLANT` | `farm` | `item`, `plot_id` | Consumes one seed and creates a growing plot on arrival. |
| `HARVEST` | `farm` | `plot_id` | Runs a 2.5-second backend activity, grants the crop, and clears the plot. |
| `FISH` | `lake` | `{}` | Runs the resolved 5–15 second activity and grants the fixed catch. |

`WAIT`, stage proposals/responses, transfers, money requests/responses, and
conversation are agent decisions but are not all physical `/tasks` actions.
Economy decisions use dedicated `/economy` routes.

### Primary integration endpoints

- State: `GET /world`, `/robots`, `/robots/{id}`, `/market`, `/economy`,
  `/tasks`, and `/tasks/{id}`.
- Commands: `POST /goal`, `/game/start`, `/game/stop`, `/game/reset`, and
  `/tasks`.
- Economy: `POST /economy/transfers`, `/economy/money-requests`, money-request
  responses, unlock proposals, and unlock responses.
- Robotics: robot pose, health, arrived, blocked, stop, and resume routes.
- History: `GET /events` and `GET /robots/{id}/history`.
- Live state: WebSocket `/events` sends complete snapshots.
- Spectator conversation: `GET /agent-chat`, WebSocket `/agent-chat/events`, and
  local traffic publication through `POST /agent-chat/traffic`.
- Interactive API documentation: `/docs` while the backend is running.

Use [`api.md`](api.md) for exact payloads, responses, and error meanings. Do not
silently rename fields or change shared request/response semantics.

## Autonomous decision behavior

The current deterministic planner roughly prioritizes:

1. Respond to pending stage or money requests involving this robot.
2. Propose the next eligible and affordable cooperative stage unlock.
3. Sell owned sellable inventory.
4. Harvest an unclaimed ready plot.
5. Plant an owned seed in an unclaimed empty plot.
6. Buy the highest-return feasible unlocked seed when capacity needs it.
7. Request the exact shortfall for that seed when a teammate can cover it.
8. Fish when there is no better feasible crop action.
9. Wait when a pending cooperative response must arrive first.

The planner accounts for teammate tasks, claimed plots, owned/reserved seeds,
pending purchases, stage locks, stock, wallet balances, crop profit rate, and
fishing expected value. Gemini receives the same bounded choices and world facts.
Neither planner may claim that an action succeeded until backend state confirms
it.

## Persistence model

The five durable tables are:

| Table | Purpose |
| --- | --- |
| `world_state` | Latest complete authoritative snapshot per session. |
| `robot_events` | Accepted semantic game events; a Tiger hypertable. |
| `robot_positions` | Changed pose observations; a Tiger hypertable. |
| `event_ids` | Session-wide duplicate-event protection. |
| `event_order` | Stable revision/ordinal order when timestamps match. |

SQLite is the default for local development. Setting `DATABASE_URL` selects
PostgreSQL/Tiger and does not silently fall back to SQLite on failure. Database
credentials and API keys belong only in ignored local files or exported
environment variables.

No retention policy is configured yet. Historical sessions accumulate until the
team agrees on cleanup/retention behavior.

## How to run the current project

### Backend simulation

From `backend/`:

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
GAME_MODE=simulation AUTONOMY_ENABLED=true AUTONOMY_PROVIDER=mock \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then start the round from the dashboard or:

```sh
curl -X POST http://127.0.0.1:8000/game/start
```

Use `AUTONOMY_PROVIDER=gemini`, `GOOGLE_API_KEY`, and
`GOOGLE_GENAI_USE_VERTEXAI=FALSE` for real Gemini decisions. Never commit the
key. The browser does not need or receive it.

### Frontend

From `frontend/` with Node 24:

```sh
nvm use
npm ci
npm run dev
```

The default backend is `http://localhost:8000`. Set `VITE_API_BASE_URL` in an
ignored frontend environment file when the server is elsewhere.

### Database setup and checks

From `backend/`:

```sh
.venv/bin/python -m app.persistence init --env-file .env
.venv/bin/python -m app.persistence check --env-file .env
```

The env file is only loaded when explicitly supplied. Exported variables take
precedence.

### Hardware mode

Start the backend with `GAME_MODE=hardware` and the calibrated game profile, then
run the fleet bridge on the camera/BLE laptop:

```sh
.venv/bin/python -m app.navigation --camera 1 --phase 4 \
  --robots-config navigation_robots.json \
  --traffic-config traffic_config.json \
  --backend-url http://127.0.0.1:8000
```

Do not use sample calibration for motion. Follow the staged procedure in the
navigation README, run only one BLE controller, and require the camera operator
to arm motion deliberately.

## Verification state

The project has automated coverage for world validation, APIs, tasks, market
rules, crops, fishing, economy commands, autonomy, simulation, persistence,
telemetry, robotics safety, vision, navigation, traffic, and HTTP integration.

Verification performed against the merged `gameLogic` branch for this handoff:

- **224 backend tests passed**.
- **1 live Tiger credential-dependent test skipped** because
  `TEST_DATABASE_URL` was not configured.
- **Frontend production build passed** with Vite and Node 24.
- **The end-to-end local HTTP smoke flow passed**, including server startup,
  task progression, persistence, and API responses.

Standard handoff commands:

```sh
cd backend
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests
PYTHONPATH=. .venv/bin/python tests/http_smoke.py

cd ../frontend
npm run build
```

The live Tiger test is intentionally skipped unless `TEST_DATABASE_URL` is set.
Automated tests cannot prove real motor direction, BLE reliability, stopping
distance, camera alignment, firmware flashing, or a live Gemini account.

## Remaining work and recommended order

### Priority 1 — Complete the physical acceptance path

This is the largest gap between the working simulation and the intended robotics
demo.

- Flash and compile the command-expiry watchdog firmware for both robots.
- Verify each robot's real motor pins, advertised BLE name, marker ID, heading
  offset, and left/right turn direction.
- Fix the overhead camera, measure arena/building bounds, measure both robot
  radii, and review traffic calibration.
- Copy `backend/game_config.json`, replace the four named service points with
  measured safe stops, and launch with `GAME_CONFIG_PATH` pointing at that copy.
- Measure conservative maximum speed, localization delay, BLE stop latency, and
  coasting distance before marking traffic calibration reviewed.
- Run phases 1–3 for both robots before allowing phase-4 motion.
- Confirm fresh pose/health updates, stop/resume, blocked handling, stale
  tracking, arrival idempotency, task cancellation, and reset behavior.
- Run the complete Repair Fund scenario first with mock autonomy and then with
  Gemini.

Exit condition: switching from simulation to hardware changes the movement
source but not game rules, frontend behavior, inventory, economy, or victory.

### Priority 2 — Optional presentation polish

- Add stage-specific farm/map artwork for Wheat, Carrots, and Pumpkins if time permits.
- Consider a short completed-crop history if rehearsal shows completed work
  disappears too quickly for spectators.
- Add sound only if it helps in the actual demo environment.

The required objective, current stage, pending cooperation, robot readiness, and
victory are now visible without reading logs.

### Priority 3 — Verify balance against physical pacing

- Keep deterministic seed `0` and the measured approximately 88-second
  simulation round as the reliable demonstration baseline.
- Measure actual travel, turn, and stop times after physical calibration.
- Use a copied game profile to adjust service points or economy/timing values if
  the guarded physical round falls outside 60–120 seconds.
- Test additional fishing seeds as rehearsal coverage, without changing the
  deterministic fallback unless the measured evidence supports it.

### Priority 4 — Rehearse Gemini behavior

- Run repeated real-provider rounds with the current prompt and model.
- Verify that messages stay concise, grounded, nonrepetitive, and useful to a
  spectator.
- Confirm that Gemini uses exact money shortfalls, respects pending requests,
  avoids duplicate plots/purchases, and does not claim unconfirmed results.
- Retain mock autonomy as the fallback demo path even if Gemini becomes the
  preferred presentation mode.

### Priority 5 — Production hardening after the demo works

- Decide database retention/history policy.
- Add deployment authentication only when leaving the trusted local network.
- Decide whether cumulative availability of earlier seeds is permanent.
- Revisit inventory transfer only if playtesting proves money transfer is not
  sufficient; it is intentionally deferred today.
- Avoid unrelated refactoring until the complete hardware demonstration is
  reliable.

## Open design decisions

- Whether physical travel measurements require changes to the validated
  approximately 88-second simulation profile.
- Whether earlier seeds stay purchasable after later stages unlock. The current
  implementation is cumulative.
- Whether only the planter should be allowed to harvest. The current shared-plot
  design allows either robot to harvest a ready unclaimed plot.
- Whether an explicit user cancellation endpoint is useful in addition to the
  implemented 30-second automatic expiration.
- Long-term proposal/request/event retention.
- Whether the Crop Queue needs completed-history cards.
- Whether a countdown loss condition adds value after hardware reliability is
  proven.

## Risks and integration cautions

- **Secrets:** never commit `.env`, Gemini keys, database URLs, BLE identifiers
  that are private to one machine, or service credentials.
- **Schema drift:** schema version 4 is shared by backend, frontend fallback,
  agents, tests, and docs. Update all consumers together for contract changes.
- **Duplicate effects:** always reuse a request ID only for a retry of the exact
  same intent. A new action requires a new ID.
- **Hardware authority:** arrival begins/completes backend work; navigation never
  grants inventory or gold.
- **Safety:** network stop is not a substitute for the ESP32 command-expiry
  watchdog. Never run multiple BLE controllers simultaneously.
- **Calibration:** `calibrated: true` must represent measured physical values,
  not an attempt to bypass a blocked route.
- **Frontend fallback:** local demo state is useful for presentation, but backend
  state is authoritative whenever a backend is selected.
- **Planner messages:** conversation is spectator context, not an alternate
  command channel.
- **Database selection:** a configured PostgreSQL URL is required to work; the
  backend does not hide its failure by falling back to SQLite.

## Definition of a complete demo

The project should be considered demo-complete when all of the following are
true:

1. Both robots begin from a known, safely calibrated physical state.
2. Backend autonomy assigns complementary work without browser ownership.
3. Real navigation follows tasks and reports fresh telemetry and confirmed
   arrivals.
4. Farming and fishing rewards occur once, only after valid arrival and timing.
5. Each robot sells only its own inventory and keeps its own wallet.
6. The robots visibly request/transfer money or jointly fund stage progression
   when required.
7. Stage 2 and Stage 3 unlock exactly once without duplicate deduction.
8. Combined gold reaches the target after Stage 3 and completes the game.
9. The UI clearly celebrates victory and explains the path taken.
10. Stop, reset, blocked, stale tracking, disconnect, and command expiry halt
    motion and prevent cancelled rewards.
11. Refreshing or reconnecting reconstructs the same authoritative state.
12. The scenario passes repeatedly with mock autonomy and at least one rehearsed
    Gemini run.

## Key implementation milestones in repository history

The exact Git log remains the source for individual commits. These are the major
milestone commits that explain the current architecture:

| Commit | Milestone |
| --- | --- |
| `9721b6c` | Initial game/robotics API contract. |
| `4559c97`, `90088d8` | Backend persistence/world API and Tiger history foundation. |
| `c8693fc` | Standalone overhead ArUco tracking. |
| `1d191e2` | Per-robot ADK agent orchestration. |
| `3ce3e19`–`c7d6a08` | Authoritative world, task assignment, simulation, collection, and market transactions. |
| `caf1dca`–`ece0c2e` | Pose/health/arrival/blocked ingestion, safety controls, modes, and freshness. |
| `42fbdff` | Backend-owned autonomous play. |
| `5c0a0dd`–`face510` | Game status, market progression, dashboard layout, Crop Queue, and notifications. |
| `809e90e`–`ec9ad11` | Farm plots and complete automated plant/grow/harvest queue. |
| `cca4eef`, `84a3962`, `f34c4ee` | Two-robot traffic control, backend hardware bridge, obstacle calibration, and enforced bounds. |
| `cd6d2ab` | Carrot and Pumpkin lifecycles. |
| `bc1603c` | Cooperative stage economy and money workflows. |
| `6eb14fc` | Strategic seeded fishing and farming-vs-fishing decisions. |
| `2da2936` | Database setup/check tooling and expanded persistence verification. |

## Instructions for teammates and other Codex sessions

Before changing this project:

1. Read this file, then the specialized document for your subsystem.
2. Run `git status` and preserve all existing uncommitted work.
3. Pull/rebase the newest shared changes; stop on ambiguous conflicts.
4. Treat `api.md` and schema version 4 as contracts.
5. Keep high-level agent decisions separate from deterministic navigation and
   physical motor safety.
6. Make the smallest focused change that advances the end-to-end demo.
7. Update tests, consumers, examples, and docs together when changing a shared
   field or behavior.
8. Run the relevant backend tests and frontend build.
9. Commit and push without including secrets or unrelated teammate changes.
10. Record the new status and remaining gap here when a milestone materially
    changes.
