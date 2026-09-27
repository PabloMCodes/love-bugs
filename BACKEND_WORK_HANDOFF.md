# Backend work handoff

Updated: 2026-09-27. Active work branch: **main**, upstream **origin/main**.
At the user's request, backend work through `d138fad` was integrated into main
with a fast-forward merge. Continue on main unless a new branch is requested.
Merge verification also corrected the autonomous-round test to collect unlock
events throughout the run instead of assuming they remain in the bounded final
snapshot. Game behavior is unchanged.

## Objective and ownership

### Physical run: unexpected disarming diagnostics

The latest camera-laptop log starts after both robots stopped: BLE connected,
both markers tracked, targets still hundreds of pixels away, backend session
disabled, and only S commands sent. It cannot establish motor direction or the
original stop trigger. Navigation now preserves `LAST DISARM` until successful
explicit backend arming, logs current backend arm rejection reasons, identifies
missing markers by name, and suppresses routine HTTP request logging. This is a
diagnostic improvement, not a verified fix to the physical stoppage. Existing
stop rules remain: fleet marker loss immediately disarms both, and backend world
expiry (0.75 seconds) also revokes permission. Next test: capture the first
`DISARMED`/`LAST DISARM` line after movement. Separately verify physical front,
heading offset and turn direction on WALL-Y before changing robot calibration.
Verification: 242 backend tests completed successfully (one live database test
skipped); no physical camera/BLE test available on the implementation laptop.

### Hardware-paced gameplay integration

The current user wants the web game to follow physical robots, using the tested
full-camera direct-driving mode without collision/boundary logic or battery
gameplay. The existing backend owns agents and game rules; no replacement planner
or motor API was added. See backend README for the three-terminal runbook.

Implemented: distinct camera timestamps, arrival evidence spanning 0.3 seconds
after STOP, latest pose/task/session checks before delivery, hardware availability
checks at arrival acceptance, and NAVIGATING status from camera telemetry. Queued
arrivals clear on disarm. Normal controller exit attempts backend game stop after
BLE stops. The frontend now waits for backend data by default, safely handles null
poses, labels camera-driven mode, and removes the battery display. Optional browser
demo requires VITE_LOCAL_DEMO=true; battery API fields remain compatible and null
on hardware. /health is only the existing BLE/readiness heartbeat.

The new test_hardware_gameplay.py drives the actual HTTP bridge and task follower
with synthetic camera frames and fake BLE state. It covers two agent BUY tasks,
no simulated travel/rewards before arrival, intermediate UI-world poses, planting,
growth, harvesting, sales, fishing, duplicate arrival and game stop. This is
software integration evidence, not a physical hardware or live Gemini pass.
The remaining operator step is a full run on the camera laptop; do not promise
zero hardware errors from tests. Keep preset locations, camera, heading offsets,
and robot IDs consistent with the already working local movement test.

Verification for this integration: 239 tests ran successfully (one live Tiger test
skipped), real HTTP/WebSocket smoke passed, Node 24/Vite production build passed,
and rendered-component checks passed null-pose startup, measured map coordinates,
tracked count, and no battery display. Live Gemini, live Tiger and the full physical
round remain unverified on this implementation laptop. The user has explicitly
deprioritized avoidance, boundaries, parking and battery/health gameplay: do not
resume those workstreams merely because the historical plan lists them.

### Named destination selection

Latest user-requested mode: `--layout full-camera --disable-avoidance` draws a
full-frame grid and preset service points without loading/modifying traffic JSON.
`FULL_CAMERA_LOCATIONS` defines fractional coordinates; they scale to live capture
dimensions. Robot targets clear and disarm on resolution changes. Destination
circles/labels were enlarged. The bypass removes boundary/building/peer/reservation
and predictive-clearance logic, allowing simultaneous direct driving, while
tracking/BLE/SPACE/arrival stops remain. Pair backend mode with
`HARDWARE_LAYOUT=full-camera` (takes priority over the saved config). Omitting the
options preserves normal calibrated behavior. Physical verification is pending.

Temporary operator-requested override: `--ignore-arena-boundary` permits fleet
travel outside the saved arena while keeping the robot inside the camera frame
with clearance. Building/peer checks and all existing stop gates remain. The
override is per-process, visibly labeled, and never edits calibration or destination
coordinates. Omit the flag to restore normal bounds. This addresses the reported
stop caused by Eeva at x≈1146 near the saved right edge of 1170.

Added `DestinationController.go_to_location(robot_id, location)` in navigation's
`fleet.py` to select saved service coordinates on the existing robot controllers.
Local fleet phases 2–4 now accept W/E then keys 1–4 for homebase/farm/lake/market;
phase 4 still requires A after local selection. Invalid known-robot selections
disarm that robot. No second BLE client or bypass of the existing guard was added.
Backend agents already submit named tasks; the task follower now shares
`RobotControl.set_target` with local selection. Local shortcuts cannot override
backend tasks. See navigation README for the function and task payload examples.
Waiting/parking and stronger arrival validation remain separate outstanding work.

### Latest continuation after pulling `3493845`

Implemented the SPACE-to-backend stop slice without changing camera-owner geometry.
`BackendBridge.request_stop()` latches pending stop intent, clears queued arrivals,
and invalidates motion authority. The asynchronous bridge prioritizes delivery and
retries failed requests. The follower rejects A while acknowledgement is pending.
`POST /game/stop` now accepts an optional session_id body; existing bodyless browser
calls still work. The world checks session identity under its lock so retries from
an old session cannot stop a replacement game. Recovery requires game start plus A.

This covers operator SPACE while the adapter is running. It does not complete
settled-arrival validation, automatic fault/exit propagation, or persistent stop
intent across process exits. Quitting while a stop is pending logs a warning.
The backend cannot process an unreachable stop; its telemetry watchdog remains a
fallback during the outage. Next implement fresh/settled arrival validation and
test one backend-directed task, while Joet completes the local calibration review.

Files touched: navigation backend/fleet, backend schemas/routes/state, traffic
tests, API contract and operating guides. No firmware, calibration, database schema,
frontend, or Gemini decision changes in this slice.

Verification for this continuation: full suite passed 227 tests with one live
Tiger test skipped; after adding one additional background-retry case, all 16
traffic tests passed. HTTP/WebSocket smoke also passed. Fault-injection coverage
includes failed stop delivery/retry, active fishing cancellation, no post-stop
reward, old-session rejection, bodyless browser compatibility, and blocked re-arm.
No physical hardware or live Tiger/Gemini verification was performed here.

Complete a physical game loop for WALL-Y and Eeva: overhead ArUco observations →
backend world → per-robot agent decisions → validated tasks → deterministic
navigation/BLE → confirmed arrival → backend inventory/gold/progression → live UI.

Reuse the existing FastAPI backend, agents, camera worker, BLE controller, and
traffic planner. Do not replace working ESP32 communication. Gemini chooses
high-level work; it does not drive motors or authorize collision clearance.

Read CAMERA_ORCHESTRATION_PLAN.md for the integration audit and acceptance ladder,
CAMERA_SETUP_GUIDE.md for operating instructions, and api.md for shared contracts.
PROJECT_STATUS.md describes the merged farming/economy baseline. PROJECT_HANDOFF.md
contains older historical context and must not override current code.

## Completed on this branch

- `cef7ce6`: audited camera/agent/backend integration, documented implementation
  order, and corrected the stale claim that the hardware bridge did not exist.
- `01eaf94`: added named service and waiting points to the existing calibration
  editor and traffic JSON; added point clearance validation and live overlays.
  The hardware backend loads service locations via HARDWARE_TRAFFIC_CONFIG.
  Navigation checks its map agrees with the backend before telemetry/task following.
- `43f1c52`: teammate's latest traffic geometry, pulled before this handoff.
  Preserve this file and any newer camera-laptop edits.

Implementation files:

| Files | Role |
| --- | --- |
| `backend/app/navigation/calibrate.py` | Frozen-image editor; service keys 1–4, waiting keys 5–8; atomic save with conflict detection |
| `backend/app/navigation/traffic.py` | Saved points, robot/wall/building clearance, required-point validation, world-coordinate conversion |
| `backend/app/navigation/backend.py` | Map agreement checks alongside existing world/telemetry/task bridge |
| `backend/app/navigation/fleet.py` | Requires complete destinations in backend mode; renders destination overlays |
| `backend/app/config.py`, `backend/app/main.py` | HARDWARE_TRAFFIC_CONFIG loading into the existing world map at startup |
| `backend/tests/test_traffic_calibration.py`, `test_traffic.py`, `test_navigation_fleet.py` | Editor, map/reset, transport and pre-connection validation coverage |

Waiting points are **saved and displayed only**. Automatic waiting, parking, and
service-point reservations are not implemented. Backend arrival/stop hardening
from the plan is also still outstanding. This is not a completed physical round.

## Latest camera-laptop evidence and next physical gate

The user configured points on Joet's camera laptop and reported seeing route lines.
Phase 3 does not move robots or connect to BLE. The latest reported message was:

`ARM REJECTED: Tracking; check BLE connection`

In `RobotControl.arm`, arming requires a visible pose, valid target, non-null BLE
controller, and connected BLE link. With the reason `Tracking`, pose/target were
available when observed; check the running phase and BLE status first. Pressing A
in phase 3 produces rejection because there is no BLE controller. If this happened
in phase 4, collect the actual startup connection logs and window BLE statuses.
We have not received those logs or confirmation of successful phase-4 movement
after the calibration change. Do not claim a diagnosed BLE defect yet.

Joet's repository is not at `~/Desktop/love-bugs`; that guessed path failed.
Use the actual backend directory opened through Finder/Terminal. Invoke
`.venv/bin/python` there rather than relying on a globally installed `python`.

**Calibration discrepancy:** the file committed in `43f1c52` has a 1920×1080 frame,
arena `[569,292,1185,762]`, three obstacles, radii 16/13 pixels, margin 30,
max_speed 250, stop_latency 1.1, and `calibrated: false`. It contains **no
service_points or waiting_points**. The user's locally saved named points may be
in another file/path or an uncommitted copy. Locate the actual saved file before
editing or pulling over local calibration. Do not invent points or enable movement
by changing the flag from this laptop. Measurements and readiness need confirmation
on the physical setup, especially that radii cover the full robot, not just its marker.

### Current calibration evidence

The camera laptop's newer `backend/traffic_config.json` was inspected and passed
`TrafficConfig.validate_destinations()`. This handoff commits that hardware-owner
configuration so another Codex sees the same geometry. Its current values are:

- frame 1920×1080; arena `[516,269,1170,772]`;
- radii 16/13 pixels, margin 30, max speed 250 px/s and stop latency 1.1 s;
- all four service points present;
- all four waiting points present;
- no obstacle rectangles; and
- `calibrated: true`.

The service/waiting minimum separation is `16 + 13 + 30 = 59` pixels. Measured
pairs now clear it: farm 108.3 px, homebase 197.0 px, lake 112.3 px and market
118.0 px. Software validation does not prove the physical measurements. Confirm
that an empty obstacle list is intentional, both radii cover the complete chassis
and attachments, and speed/latency are conservative measured bounds. The user was
given the guarded phase-4 procedure, but no successful phase-4 movement result or
logs have been reported in this conversation. The next operator must not claim a
physical pass until testing one robot, the other robot, then a two-target queue
with SPACE immediately available.

## Database integration status

The application already keeps persistence behind the authoritative backend. The
frontend, camera/navigation bridge and agents use HTTP/WebSocket or in-process
world services; they must not connect directly to SQLite/Tiger. Every accepted
`WorldStore` transition is written before it becomes visible in memory. Current
persistence covers complete world snapshots, semantic events and changed robot
poses, which includes tasks, lifecycle, crops, fishing outcomes, inventory,
wallets, cooperative economy, pose/health/blocked/arrival effects and resets.

The five initialized tables remain `world_state`, `robot_events`,
`robot_positions`, `event_ids` and `event_order`. Spectator chat, raw camera frames,
individual BLE commands and calibration JSON are deliberately outside those
tables. Chat is currently bounded in memory; persisting it would be a separate
contract/schema decision. Raw frames and motor commands should not be placed in
the authoritative game database.

Verified on this checkout:

- `backend/lovebugs.sqlite3` exists locally, is ignored by Git and is the default
  backend because no `DATABASE_URL` is configured;
- the ignored `backend/.env` contains agent/frontend configuration but no
  `DATABASE_URL`, `TEST_DATABASE_URL` or `SQLITE_PATH`;
- isolated SQLite `app.persistence init` and `check` reported all five tables ready;
- persistence tests ran 6 cases: 5 passed and the credential-dependent live Tiger
  case skipped;
- the real HTTP/WebSocket smoke passed gameplay/persisted history,
  pose/health/world socket, mock chat/CORS and lifecycle flows; and
- the user separately ran `init` and `check` against the default local SQLite file
  and reported the same ready schema.

Live Tiger remains unverified. To test it, place `DATABASE_URL` and
`TEST_DATABASE_URL` only in the ignored local environment, run `init` and `check`,
then run the isolated-schema persistence test. Do not paste or commit credentials.
Use SQLite for the first physical task slice so database/network latency is not
confused with camera/BLE integration; repeat against Tiger afterward and measure
telemetry/write latency.

## Immediate operating sequence

From the actual `backend` folder on the camera laptop:

```sh
# Camera/geometry preview; no BLE or physical movement:
.venv/bin/python -m app.navigation --camera 1 --phase 3 --robots-config navigation_robots.json --traffic-config traffic_config.json

# After geometry review and successful dry run, close phase 3 with Q:
.venv/bin/python -m app.navigation --camera 1 --phase 4 --robots-config navigation_robots.json --traffic-config traffic_config.json
```

In phase 4, wait for both BLE links. W selects WALL-Y, E selects Eeva; click a clear
target and press A to arm the selected robot. SPACE stops both; Q stops and exits.
Close other BLE controllers. Inspect TRAFFIC stop reasons rather than disabling
the guard. Test one robot first, then both. There is no backend task following
without `--backend-url`.

For named-point setup, use:

```sh
.venv/bin/python -m app.navigation.calibrate --camera 1 --config traffic_config.json
```

SPACE freezes the image. Set arena/buildings/robot footprints, then 1/2/3/4 select
homebase/farm/lake/market service points; 5/6/7/8 select matching waiting points.
Click clear floor beside buildings. S saves and intentionally sets calibrated=false.
Review geometry and measurements before manually enabling the calibration.
Changing camera position, zoom, or resolution requires recalibration.

## Implementation process and next steps

1. **Physically verify the committed calibration and BLE movement.** Confirm the
   actual branch/config path, marker IDs, headings and both BLE states. Check that
   zero obstacles is intentional and that radii, speed and stop latency match the
   physical setup. Repeat phase 1/3 if anything moved, then test guarded phase 4:
   WALL-Y alone, Eeva alone, and finally two queued targets. Record logs and stop
   behavior; do not infer success from the software validator.
2. **Complete a backend-directed single-task slice.** Use the same complete traffic
   file on camera/backend laptops. Start hardware mode with
   `HARDWARE_TRAFFIC_CONFIG=./traffic_config.json`; copy the file if hosts differ.
   Add `--backend-url http://BACKEND_HOST:8000` to navigation, inspect `/world`
   map agreement, start the game, and deliberately arm with A. Begin with manually
   submitted backend tasks/autonomy disabled to isolate the adapter.
3. **Harden arrivals and stops before autonomous rewards.** Require fresh, settled,
   stopped arrival for the current task/session; invalidate stale queued reports.
   Add backend hardware arrival validation. SPACE now propagates backend game stop
   asynchronously while retaining immediate local stop and deliberate recovery.
   Extend this to other interruption/exit paths and test physical interruptions
   during activity; do not assume the SPACE slice completes all safety integration.
4. **Improve bridge scheduling/freshness.** Deduplicate observations using capture
   timestamps; separate chat retries from control authority, bound HTTP work, and
   report persistent blocked reasons through the existing contract.
5. **Implement service reservations and parking.** Use saved waiting points with
   deterministic right of way and progress checks. Current whole-trip traffic
   reservation does not solve an occupied destination. Chat should explain the
   selected safe decision; model response time must not control motor safety.
6. **Run mock then Gemini gameplay.** Verify real BUY → PLANT → grow → HARVEST →
   SELL and FISH → SELL, then two-robot progression through Stage 3 and the gold goal.
   UI must reflect confirmed backend state, not dialogue claims or offline fallback.
7. **Repeat with Tiger Data and measure latency.** Keep all database writes behind
   the backend. Live Tiger, live Gemini and physical hardware require separate
   evidence; successful unit tests do not verify them.

Make each slice independently reviewable. Inspect status and pull/rebase before
work; stop on ambiguous conflicts. Update contracts/docs/tests with shared changes.
Commit and push completed work to origin/main. Update this handoff with actual
evidence and remaining work after each slice; distinguish reported results from
personally verified results. Do not overwrite teammate calibration or secrets.

## Verification record

For `01eaf94`: 224 unit tests ran successfully, including one skipped live Tiger
test. The HTTP/WebSocket smoke passed gameplay, persistence history, telemetry,
chat, CORS and lifecycle checks. No real camera, motors, Gemini or Tiger service
were exercised on the implementation laptop. The teammate geometry commit was
reviewed but not physically validated there. The earlier `8a14d30` handoff changed
documentation only; the current handoff also commits the newer traffic configuration.

For the current configuration handoff, destination validation passed with all
eight named points and the separations recorded above. This is configuration
validation only; phase-4 movement is still awaiting reported physical evidence.

Commands from backend:

```sh
.venv/bin/python -m unittest discover -s tests -q
PYTHONPATH=. .venv/bin/python tests/http_smoke.py
```

The other chat should start with `git status`, then `git pull --rebase` on main.
If local calibration prevents a safe pull, preserve it and report the conflict;
never reset or overwrite it to make the pull succeed.
