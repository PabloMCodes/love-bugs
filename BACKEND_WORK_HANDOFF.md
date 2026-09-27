# Backend work handoff

Updated: 2026-09-27. Active work branch: **backend**, upstream **origin/backend**.
Continue work here; do not merge or switch implementation to main without a request.

## Objective and ownership

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

## Latest camera-laptop evidence and current blocker

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

1. **Resolve the current operating issue and calibration mismatch.** Confirm the
   actual branch, absolute config path, phase, marker IDs and BLE states. Preserve
   local calibration. Verify both robots can execute guarded clicked targets.
2. **Complete a backend-directed single-task slice.** Use the same complete traffic
   file on camera/backend laptops. Start hardware mode with
   `HARDWARE_TRAFFIC_CONFIG=./traffic_config.json`; copy the file if hosts differ.
   Add `--backend-url http://BACKEND_HOST:8000` to navigation, inspect `/world`
   map agreement, start the game, and deliberately arm with A. Begin with manually
   submitted backend tasks/autonomy disabled to isolate the adapter.
3. **Harden arrivals and stops before autonomous rewards.** Require fresh, settled,
   stopped arrival for the current task/session; invalidate stale queued reports.
   Add backend hardware arrival validation. Local SPACE currently disarms motors
   without propagating backend game stop; fix that asynchronously while retaining
   immediate local stop and deliberate recovery. Test interruptions during activity.
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
Commit and push completed work to origin/backend. Update this handoff with actual
evidence and remaining work after each slice; distinguish reported results from
personally verified results. Do not overwrite teammate calibration or secrets.

## Verification record

For `01eaf94`: 224 unit tests ran successfully, including one skipped live Tiger
test. The HTTP/WebSocket smoke passed gameplay, persistence history, telemetry,
chat, CORS and lifecycle checks. No real camera, motors, Gemini or Tiger service
were exercised on the implementation laptop. The teammate geometry commit was
reviewed but not physically validated here. This handoff changes documentation only.

Commands from backend:

```sh
.venv/bin/python -m unittest discover -s tests -q
PYTHONPATH=. .venv/bin/python tests/http_smoke.py
```

The other chat should start with `git status`, then `git pull --rebase` on backend.
If local calibration prevents a safe pull, preserve it and report the conflict;
never reset or overwrite it to make the pull succeed.
