# Camera, Localization, Navigation, and Traffic Setup Guide

This document is the shared runbook for setting up the Love Bugs overhead camera,
detecting WALL-Y and Eeva, calibrating the arena, testing navigation, enabling
physical movement, and connecting the camera process to the hardware backend.

It is written for teammates and their Codex sessions. Use it to compare proposed
changes before changing shared interfaces or allowing physical motion.

## 1. Scope and system ownership

The camera stack has several separate responsibilities. Keeping them separate is
important when debugging:

| Component | Responsibility | Does not own |
| --- | --- | --- |
| `app.vision.capture.VideoSource` | Opens a live camera or video and returns frames | Marker identity, movement, game state |
| `app.vision.localization.ArucoTracker` | Detects ArUco markers and calculates centers/headings | BLE commands, task completion |
| `app.navigation.controller` | Converts a pose and target into `F/L/R/S` intent | Collision avoidance, backend state |
| `app.navigation.fleet` | Runs two robots with mandatory traffic bounds, camera UI, arming, BLE, and optional backend bridge | Authoritative inventory, gold, rewards |
| `app.navigation.traffic` | Reserves one moving robot, checks clearances, and plans bounded detours | Contact sensing or guarantees about unmodeled obstacles |
| `app.navigation.backend` | Publishes pose/health and follows authoritative backend tasks | Game rules or motor-safety decisions |
| FastAPI backend | Owns sessions, tasks, arrivals, inventory, gold, game state, and events | Camera pixels or direct motor output |
| ESP32 firmware | Applies motor commands and must stop locally when commands expire | Navigation planning or game decisions |

The camera process is a hardware adapter. It must never calculate authoritative
game rewards or update the database directly.

## 2. Relevant files

- `backend/app/vision/capture.py`: live camera/video acquisition.
- `backend/app/vision/localization.py`: `DICT_4X4_50` marker detection.
- `backend/app/navigation/__main__.py`: command-line entry point and single-robot phases.
- `backend/app/navigation/fleet.py`: two-robot UI, BLE, traffic, and backend bridge.
- `backend/app/navigation/controller.py`: steering and safety gate.
- `backend/app/navigation/traffic.py`: calibrated collision clearance and detours.
- `backend/app/navigation/backend.py`: hardware-world polling and telemetry reporting.
- `backend/app/navigation/calibrate.py`: visual arena/building/robot measurement tool.
- `backend/navigation_robots.json`: per-robot marker, steering, and BLE settings.
- `backend/traffic_config.json`: camera geometry and traffic safety measurements.
- `backend/app/navigation/README.md`: lower-level implementation reference.
- `api.md`: stable backend contract.
- `INTEGRATION.md`: teammate integration checklist.
- `firmware/wall_y_watchdog/wall_y_watchdog.ino`: optional command-expiry firmware.

## 3. Safety rules

Before running any command that can move a robot:

1. Put both robots on the floor inside a clear, bounded test area.
2. Keep wheels off the ground for the first motor-direction test.
3. Ensure a person can immediately press **SPACE**, switch robot power off, or
   disconnect motor power.
4. Close `ble_control.py`, old navigation windows, phone BLE tools, and any other
   controller. Only one process may own each robot connection.
5. Do not use phase 4 until phases 1–3 are correct.
6. Do not enable traffic movement until `traffic_config.json` has been physically
   measured, reviewed, dry-run, and deliberately marked `"calibrated": true`.
7. If either marker disappears, a camera frame becomes stale, BLE disconnects,
   the backend becomes stale, or traffic reports unsafe geometry, both robots
   must remain stopped until a person resolves the fault and re-arms them.
8. Traffic control is not contact sensing. It cannot detect an obstacle that is
   absent from the static calibration and not represented by the other marker.
9. Do not move, zoom, rotate, or mirror the camera after calibration. Recalibrate
   if any of those change.

## 4. One-time software setup

Run commands from the repository root unless a section says otherwise.

```sh
cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

On macOS, allow the terminal application that launches Python to access:

- Camera
- Bluetooth
- Local Network, when the backend is on another laptop

These permissions are managed under **System Settings → Privacy & Security**.
Restart the terminal after changing permissions.

Confirm OpenCV has a desktop window backend:

```sh
.venv/bin/python -c "import cv2; print([line for line in cv2.getBuildInformation().splitlines() if 'GUI:' in line])"
```

The current Mac build should report `COCOA`.

## 5. Turning on the physical system

There is no software command that physically powers the robots or camera.

1. Power the overhead camera or make the iPhone Continuity Camera available.
2. Mount it rigidly above the complete arena with an unmirrored, approximately
   perpendicular view.
3. Power WALL-Y and Eeva using their hardware power controls or USB power.
4. Wait for their ESP32 BLE advertisements:
   - WALL-Y advertises `WALL-Y`.
   - Eeva advertises `Eeva`.
5. Place ArUco marker ID `0` on WALL-Y and marker ID `1` on Eeva, matching
   `navigation_robots.json`.
6. Make the markers flat, unobstructed, high contrast, and large enough to remain
   detectable throughout the arena.

The fleet code discovers both names in one scan and passes the resulting
machine-local `BLEDevice` objects into Bleak. Do not commit macOS UUIDs: they are
specific to the scanning Mac.

## 6. Find and verify the camera index

Start with camera index `1`, which has returned 1920×1080 frames on the current
camera laptop. If the hardware changes, compare indexes safely in phase 1:

```sh
cd backend
.venv/bin/python -m app.navigation --camera 0 --phase 1 --robots-config navigation_robots.json
.venv/bin/python -m app.navigation --camera 1 --phase 1 --robots-config navigation_robots.json
```

Only run one command at a time. Close each window with **Q** before testing the
next index.

Expected phase-1 result:

- A window titled `Love Bugs navigation` opens.
- Both visible markers receive outlines and labels.
- WALL-Y displays marker ID `0`.
- Eeva displays marker ID `1`.
- Pixel center coordinates update when a robot is moved by hand.
- Heading changes continuously and does not jump randomly while stationary.
- BLE is off and no motor commands are sent.

`Waiting for camera` means no processed frame has arrived yet. `Marker missing`
means frames are arriving, but the configured marker is not detected. These are
different failures.

## 7. Navigation phases

Always validate phases in order.

### Phase 1: localization only

```sh
cd backend
.venv/bin/python -m app.navigation --camera 1 --phase 1 --robots-config navigation_robots.json
```

Use phase 1 to verify the camera, marker IDs, center points, and raw marker
headings. It does not connect to BLE and cannot move the robots.

### Phase 2: target geometry

```sh
.venv/bin/python -m app.navigation --camera 1 --phase 2 --robots-config navigation_robots.json
```

Controls:

- **W** selects WALL-Y.
- **E** selects Eeva.
- Clicking assigns a target to the selected robot.

Use phase 2 to verify the crosshair, robot-to-target line, distance, corrected
heading, and heading error. The selected motor command remains `S`, and BLE is
still off.

### Phase 3: command-selection dry run

```sh
.venv/bin/python -m app.navigation --camera 1 --phase 3 --robots-config navigation_robots.json
```

Use phase 3 to verify that moving or rotating a robot by hand produces the
correct proposed command:

- `F`: target is ahead.
- `L`: rotate left toward the target.
- `R`: rotate right toward the target.
- `S`: arrived, unsafe, missing, stale, or not ready.

No BLE connection occurs. Fix `heading_offset_degrees` or `invert_turns` in
`navigation_robots.json` if the proposed direction is wrong.

### Phase 4: physical BLE movement

```sh
.venv/bin/python -m app.navigation --camera 1 --phase 4 --robots-config navigation_robots.json
```

Phase 4 starts the camera immediately, automatically loads the saved default
`backend/traffic_config.json`, scans once for both robots, connects sequentially,
and sends an initial STOP. Missing or invalid traffic configuration fails startup;
`"calibrated": false` keeps every movement command at STOP. To queue independent
targets for both robots after calibration:

1. Press **W**.
2. Click WALL-Y's target.
3. Press **A** to arm WALL-Y.
4. Press **E**.
5. Click Eeva's target.
6. Press **A** to arm Eeva.

Selecting the other robot does not cancel the first robot's target. Clicking a
new target disarms only the selected robot, so press **A** again after changing
its target. Mandatory traffic control permits only one robot to move at a time;
the other remains stopped until its reserved trip is safe to run.

Global controls:

- **SPACE** stops and disarms both robots.
- **Q** stops, disconnects, and closes the process.
- Closing the window or pressing Ctrl-C also attempts STOP and cleanup.

Fleet mode cannot disable traffic protection. The command above uses the saved
default configuration; `--traffic-config PATH` only selects a different saved
calibration file.

## 8. Marker heading and steering calibration

Image coordinates use:

- Origin at the upper-left.
- Positive x toward the right.
- Positive y downward.
- Heading `0°` toward image-right.
- Heading `90°` downward.
- Heading `180°` left.
- Heading `270°` upward.

For each robot:

1. Physically point its nose toward image-right.
2. Run phase 2 or 3.
3. Adjust `heading_offset_degrees` until the corrected heading points right.
4. With wheels safely raised, verify a brief proposed/physical right turn.
5. A right turn should increase the corrected image heading clockwise.
6. If left and right are reversed, toggle that robot's `invert_turns`.
7. Repeat phase 3 before allowing phase 4 movement.

The two robot profiles are independent. Do not assume one robot's mounting offset
or motor wiring matches the other.

## 9. Draw the arena, buildings, and robot footprints

Stop navigation and every BLE controller first. The calibration tool uses only
the camera and never connects to a robot:

```sh
cd backend
.venv/bin/python -m app.navigation.calibrate --camera 1 --config traffic_config.json
```

Allow exposure and focus to settle, then press **SPACE** to freeze the frame.

Calibration controls:

| Key | Action |
| --- | --- |
| **A** | Drag the usable arena rectangle |
| **B** | Drag a rectangle around a building or fixed obstacle |
| **W** | Drag WALL-Y's complete body box, then click marker center |
| **E** | Drag Eeva's complete body box, then click marker center |
| **U** | Remove the most recently added building |
| **S** | Save the measurements |
| **Q** | Quit without saving remaining edits |

When drawing:

- The arena is the drivable interior, not the entire image.
- Include walls, roofs, overhangs, decorations, and anything a robot can hit in
  each building rectangle.
- Draw the complete robot, including wheels and attachments.
- Click the marker's center only after completing that robot's body box.
- The tool calculates the largest marker-to-corner distance as the turning radius.
- The blue circle is the measured radius.
- The red circle is the radius plus the configured safety margin.

Saving always leaves `"calibrated": false`. That is intentional: saving a shape
does not authorize physical movement.

The current working tree contains calibration-in-progress at 1920×1080 with an
arena and three obstacles. Preserve `backend/traffic_config.json`; review those
measurements with the hardware team before committing or enabling them.

## 10. Review `traffic_config.json`

### Named service and waiting points

In the frozen setup image, first define arena/buildings and measure both robots.
Then use these keys and click the floor where the robot's marker center should stop:

| Destination | Service point | Waiting point |
| --- | --- | --- |
| homebase | 1 | 5 |
| farm | 2 | 6 |
| lake | 3 | 7 |
| market | 4 | 8 |

Service points belong beside buildings, not inside their obstacle boxes. Waiting
points need room for the second robot while the service point is occupied. Click
again in a selected mode to reposition it. Green circles mark service points;
blue circles mark waiting points, both in setup and the navigation window.

Press S to save `service_points` and `waiting_points` in the same traffic JSON.
Partial drafts can be saved, but backend task following requires all eight points.
Each point must clear walls/buildings for the larger robot plus the margin; a
waiting point must be separated from its corresponding service point by more than
both robot radii plus the margin. Saving still disables motion (`calibrated=false`).
Changed resolution clears these points along with old arena/building geometry.

Waiting points are saved and displayed for the next traffic integration slice;
automatic queueing/parking is not implemented yet. Endpoint validation does not
prove a route is reachable: inspect routes with the existing dry run and current
robot positions before physical movement. Local clicked-target mode remains usable
with older files without named points.

Set `HARDWARE_TRAFFIC_CONFIG=./traffic_config.json` on the backend process. If it
runs on another laptop, copy this saved file there and use its local path. The
backend publishes the calibrated service locations in `/world`; navigation checks
they match its calibration and stops on mismatch. Restart both processes after
editing geometry. Camera movement or zoom requires recalibration even if frame
resolution stays the same.

Fields:

| Field | Meaning |
| --- | --- |
| `calibrated` | Explicit human approval gate. False blocks traffic-controlled movement. |
| `frame_width`, `frame_height` | Exact captured frame resolution used for calibration. |
| `arena` | `[left, top, right, bottom]` usable bounds in camera pixels. |
| `radii` | Marker-center-to-furthest-body-corner radius for each robot. |
| `margin` | Extra localization, clearance, and measurement safety padding. |
| `max_speed` | Conservative measured upper bound in pixels/second. |
| `stop_latency` | Worst-case sensing, command, and coasting delay; minimum one second. |
| `grid` | Grid spacing used by bounded A* detour planning. |
| `obstacles` | Static rectangles in `[left, top, right, bottom]` camera pixels. |

Review checklist:

- Resolution exactly matches the live camera.
- Arena excludes walls and inaccessible edges.
- Both radii cover the complete turning sweep.
- Margin is conservative for marker jitter and physical clearance.
- Every fixed structure is represented.
- `max_speed` was measured, not guessed downward to make a route pass.
- `stop_latency` covers camera delay, BLE STOP delivery, and coasting.
- Grid has enough clearance around all corners.
- The camera has not moved since measurement.

Only after review should a human change:

```json
"calibrated": true
```

## 11. Traffic-protected dry run

Before BLE movement, inspect traffic decisions in phase 3:

```sh
cd backend
.venv/bin/python -m app.navigation \
  --camera 1 \
  --phase 3 \
  --robots-config navigation_robots.json
```

Fleet mode automatically loads `backend/traffic_config.json`. Add
`--traffic-config /absolute/or/relative/path.json` only when intentionally using
another calibration; use that identical path with the calibration editor.

Expected overlay:

- Red circles show each robot's radius plus margin.
- Rectangles show the arena and fixed obstacles.
- Green lines show the reserved direct or detour route.
- The traffic status explains which robot goes first and why the other waits.

Traffic rules:

- Both markers must be fresh and visible.
- Only one robot receives a movement reservation at a time.
- The other receives `S` and holds position.
- Planner segments are checked against the arena, expanded obstacles, and the
  other robot's footprint.
- Forward movement is checked using predicted travel through stop latency plus
  the next motor pulse.
- Priority alternates when possible.
- An impossible route, occupied destination, wrong resolution, missing marker,
  or unsafe separation stops both.

Phase 3 sends no BLE commands. Move robots by hand to exercise different routes.

## 12. Traffic-protected physical movement

After the dry run is correct:

```sh
.venv/bin/python -m app.navigation \
  --camera 1 \
  --phase 4 \
  --robots-config navigation_robots.json
```

Assign and arm both robots using W/E, click, and A. Both can have pending targets,
but traffic control intentionally moves one at a time. There is no fallback to
unguarded fleet movement.

After any traffic safety stop, correct the cause and explicitly press **A** again.
The system must not auto-resume physical motion.

## 13. Hardware backend integration

Use this only after local traffic-controlled phase 4 works.

### Terminal 1: hardware backend

```sh
cd backend
GAME_MODE=hardware \
HARDWARE_TRAFFIC_CONFIG=./traffic_config.json \
AUTONOMY_ENABLED=true \
AUTONOMY_PROVIDER=mock \
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Use `AUTONOMY_PROVIDER=gemini` only when the local API key/model configuration is
ready. The LLM proposes game tasks; it never authorizes motor safety.

### Terminal 2: frontend

```sh
cd frontend
nvm use
npm ci
npm run dev
```

Set `VITE_API_BASE_URL` when the backend is not at `http://localhost:8000`.

### Terminal 3: camera, BLE, traffic, and backend bridge

```sh
cd backend
.venv/bin/python -m app.navigation \
  --camera 1 \
  --phase 4 \
  --robots-config navigation_robots.json \
  --traffic-config traffic_config.json \
  --backend-url http://127.0.0.1:8000
```

If the backend is on another laptop, replace `127.0.0.1` with that laptop's LAN
address and allow port 8000 through its firewall.

Backend mode behavior:

- Mouse target clicks are disabled.
- The bridge polls the authoritative hardware world.
- It maps backend map locations into the calibrated camera arena.
- It publishes normalized poses and health.
- It reports confirmed arrival for the matching session/task/location.
- Backend timers and transactions grant inventory and gold.
- Press **A** once to enable following backend tasks for both robots.
- **SPACE**, stale backend data, game stop/reset, a traffic fault, stale tracking,
  or a lost BLE link revokes motion permission.
- A human must press **A** again after an interruption.

Do not run a second telemetry writer or BLE controller alongside this adapter.

## 14. Expected logs and meanings

| Log/status | Meaning |
| --- | --- |
| `Scanning once for WALL-Y, Eeva` | One fleet BLE discovery is running. |
| `Resolved ...` | The advertised name was mapped to this Mac's current device object. |
| `connected; sending initial STOP` | Link succeeded; movement is still disarmed. |
| `Waiting for camera` | No processed frame is available yet. |
| `Marker missing` | Frames exist, but that configured marker was not detected. |
| `Tracking` | Marker pose is fresh. A valid target is also present. |
| `ARMED` | The local motion gate accepted explicit arming. |
| `Traffic configuration: ...` | Fleet mode loaded this saved geometry, calibration state, arena, building count, and resolution. |
| `Calibrate traffic_config.json before movement` | Approval gate is false. |
| `Camera resolution differs from traffic calibration` | Camera mode/zoom/resolution changed. |
| `Both markers required` | Traffic mode refuses movement with incomplete localization. |
| `Too close` | Robot safety circles overlap; separate them manually. |
| `No clear route` | Target or geometry is unreachable under current clearances. |
| `BACKEND: press A to enable tasks` | Bridge is healthy but local physical permission is not armed. |

Repeated `BLE ... sent S` messages are safety refreshes. They do not mean a robot
is trying to move.

## 15. Troubleshooting sequence

### Camera window does not appear

1. Confirm no old navigation process is running.
2. Run phase 1 without BLE.
3. Test camera indexes 0 and 1.
4. Check macOS camera permission for the launching terminal.
5. Look for the Python window behind VS Code or on another macOS desktop.
6. Confirm OpenCV reports the `COCOA` GUI backend.

### Window appears but reports `Marker missing`

1. Confirm the correct `DICT_4X4_50` marker IDs: 0 and 1.
2. Increase marker size or move the camera closer.
3. Improve lighting and reduce glare/motion blur.
4. Keep the complete black border visible.
5. Confirm the image is not mirrored or heavily distorted.

### BLE discovery or connection fails

1. Confirm both robots are powered and advertising unique names.
2. Close other BLE controllers and phone apps.
3. Restart the ESP32s if a previous connection did not release.
4. Confirm `ble_direct_address` remains false for portable name discovery.
5. Do not copy a UUID from another Mac into the shared configuration.

### Robot turns the wrong way

1. Stop immediately.
2. Return to phase 3.
3. Verify heading offset with the nose pointed image-right.
4. Toggle only that robot's `invert_turns` if physical L/R is reversed.

### Traffic mode never moves

Check, in order:

1. `calibrated` is deliberately true after review.
2. Live resolution matches calibration.
3. Both markers are visible and fresh.
4. Robots are inside the arena and outside expanded obstacles.
5. Robots are sufficiently separated.
6. Target is inside safe reachable space.
7. Phase 4 robot(s) were armed.
8. In backend mode, the game is running, world data is fresh, and A enabled tasks.

## 16. Verification commands before handoff

Run automated checks after camera/navigation code changes:

```sh
cd backend
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -p 'test_navigation*.py'
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -p 'test_traffic*.py'
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests
```

Automated tests use mocked BLE and generated frames. They cannot prove physical
turn direction, stopping distance, camera placement, BLE range, or obstacle
clearance. Record those physical checks separately.

## 17. Copyable prompts for teammates' Codex sessions

These prompts are designed to get independent reviews without silently changing
shared contracts or moving hardware.

### Prompt A: camera and marker audit

```text
Pull the latest main branch and inspect CAMERA_SETUP_GUIDE.md,
backend/app/vision/capture.py, backend/app/vision/localization.py,
backend/navigation_robots.json, and the navigation tests. Do not change files and
do not connect to BLE. Explain the full camera-to-pose pipeline, verify the ArUco
dictionary and marker ID mapping for robot-a/WALL-Y and robot-b/Eeva, identify
likely causes of missing or unstable detections, and give us a physical camera
validation checklist. Preserve all uncommitted calibration files.
```

### Prompt B: traffic calibration review

```text
Review CAMERA_SETUP_GUIDE.md, backend/traffic_config.json,
backend/app/navigation/calibrate.py, and backend/app/navigation/traffic.py.
Treat traffic_config.json as teammate-owned calibration data: do not overwrite,
normalize, or enable it. Explain each measured value, flag unsafe or suspicious
geometry, and list the exact physical measurements still needed before setting
calibrated=true. Check frame resolution, arena bounds, both turning radii,
obstacles, margin, max speed, stop latency, and grid size.
```

### Prompt C: navigation safety audit

```text
Inspect the two-robot navigation and traffic-control implementation. Do not run
physical movement. Trace every condition that can produce F, L, R, or S, and
verify that camera loss, stale poses, BLE loss, backend loss, game stop/reset,
traffic blockage, SPACE, Q, and exceptions all stop safely and require explicit
re-arming. Report concrete file/line evidence and any race conditions or unsafe
assumptions. Do not change the public API.
```

### Prompt D: backend hardware-bridge audit

```text
Read CAMERA_SETUP_GUIDE.md, INTEGRATION.md, api.md,
backend/app/navigation/backend.py, backend/app/navigation/fleet.py, and the
hardware-mode backend routes. Do not modify code. Diagram how session_id,
robot_id, task_id, destination, pose, health, blocked state, and arrival flow
between the backend and camera adapter. Verify that the backend remains
authoritative for task completion, inventory, gold, and rewards. Identify stale
data or idempotency risks and propose tests without changing existing schemas.
```

### Prompt E: ESP32 watchdog review

```text
Review firmware/wall_y_watchdog/wall_y_watchdog.ino together with the navigation
command frequency, refresh interval, BLE write mode, and shutdown behavior.
Do not flash hardware. Verify that boot, S, disconnect, expired commands, and a
frozen host stop the motors; H must not extend motion. Confirm device names and
motor pins must be customized per robot. List a safe bench-test procedure with
wheels raised before floor testing.
```

### Prompt F: end-to-end test plan

```text
Using CAMERA_SETUP_GUIDE.md, GAME_PLAN.md, INTEGRATION.md, and api.md, produce an
end-to-end test matrix from phase-1 camera detection through traffic-protected
hardware autonomy. Separate automated, camera-only, wheels-raised, floor,
backend, frontend, failure-injection, and acceptance tests. Include pass/fail
evidence, responsible teammate, reset procedure, emergency stop, and rollback.
Do not execute physical movement or modify files.
```

### Prompt G: diagnose a failed run

```text
Diagnose this Love Bugs camera/navigation run using CAMERA_SETUP_GUIDE.md and the
current code. Start by classifying the failure as camera opening, marker
detection, heading calibration, BLE discovery, BLE connection, arming, traffic,
backend freshness, or task mapping. Explain the earliest failing stage from the
logs before proposing changes. Do not modify calibration data or run motors.
Here are the complete terminal logs:

[PASTE LOGS HERE]
```

### Prompt H: propose a scoped implementation

```text
We have completed the camera and traffic checklist in CAMERA_SETUP_GUIDE.md.
Inspect the current working tree and preserve all teammate changes. Propose the
smallest implementation needed for this specific gap: [DESCRIBE GAP]. State the
files and shared interfaces affected, safety invariants, tests, migration or
configuration changes, and how it fits the current project scope. Do not code or
move hardware until we approve the plan.
```

## 18. Team decision checklist

Before pursuing a new camera/navigation feature, agree on:

- Is it required for the working end-to-end demo?
- Which subsystem owns the source of truth?
- Does it alter `GET /world`, `/events`, task schemas, or telemetry endpoints?
- Does it create another process that could compete for camera, BLE, or telemetry?
- What physical measurement or sensor evidence supports it?
- What failure makes the robots stop?
- What action is required to re-arm?
- Can it be tested in phase 1–3 before physical movement?
- Who owns calibration data and approves `calibrated=true`?
- What automated and physical acceptance evidence is required?

Prioritize a reliable end-to-end demo, safety, and teammate integration over a
larger unfinished autonomy feature.
