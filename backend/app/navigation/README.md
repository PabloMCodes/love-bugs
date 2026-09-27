# WALL-Y click-to-drive bring-up

Standalone local control using the existing `VideoSource` and `ArucoTracker`
(DICT_4X4_50). This does not submit game tasks or publish backend poses.
Close the manual BLE script before phase 4; run only one controller at a time.

From `backend/`, install dependencies and verify each phase **in order**:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m app.navigation --camera 0 --phase 1
.venv/bin/python -m app.navigation --camera 0 --phase 2
.venv/bin/python -m app.navigation --camera 0 --phase 3
.venv/bin/python -m app.navigation --camera 0 --phase 4
```

Use the camera index that worked for your iPhone. Allow macOS camera/Bluetooth
access for the terminal. Phase 1 is the default when `--phase` is omitted.

1. **Localization:** verify marker ID, pixel x/y, outline, center and heading.
2. **Geometry:** click a target; verify crosshair, line, distance and headings.
   Command remains S. Neither phase connects to BLE.
3. **Dry run:** move/rotate WALL-Y by hand; verify selected F/L/R/S in the window
   and logs. BLE stays off. Within `stop_distance`, selection must be S.
4. **Pulsed driving:** connects and sends S first. Click a nearby clear target,
   then press **A** to arm. Rotates, advances in pulses, and latches stopped on arrival.

Replace `--camera 0` with `--video /path/to/video.mp4` for phases 1–3. EOF exits
cleanly. Phase 4 rejects prerecorded input.

**SPACE** latches stop; **Q**, window close, Ctrl-C, errors and EOF attempt S
before disconnecting. Clicking a new target disarms; press A deliberately again.
Missing detections select S immediately. A pose older than 0.5 seconds disarms;
reacquisition does not re-arm. Capture/detection runs in a separate thread so a
stalled camera read cannot block the UI and stop checks.

BLE failure ends the run. Restart to reconnect; connection begins with S and
requires A plus fresh tracking again. BLE startup allows 30 seconds to connect and five seconds for the
initial STOP (before arming), matching the connection-only diagnostic. Motion
writes retain their 0.3-second deadline. Errors include the device, failing
operation, exception type and write settings; two-robot startup also prints the
configuration path so laptop-specific identifiers can be checked.
The supplied firmware stops on detected
disconnect. A laptop cannot deliver S over a lost link. This firmware has **no
connected command-expiry watchdog**: a frozen host with a lingering connection
cannot be guaranteed to stop in 0.5 s. Firmware is unchanged. OS, GUI and BLE
timing are best effort rather than hard real time.

## Settings and physical calibration

Edit `backend/navigation_config.json`, or use `--config /path/to/config.json`.

| Setting | Meaning |
| --- | --- |
| `camera_index`, `marker_id` | Camera and WALL-Y marker (default ID 0) |
| `target_x`, `target_y` | Initial pixel target (500, 300); out-of-frame targets cannot arm |
| `heading_offset_degrees` | Rotation from marker top edge to robot's actual forward direction |
| `invert_turns` | Swap L/R selection without changing firmware |
| `stop_distance`, `angle_threshold` | Arrival radius 35 pixels; turn threshold 15 degrees |
| `command_hz`, `refresh_seconds` | Max normal update rate 10 Hz; unchanged command refresh 0.3 s |
| `marker_timeout` | Maximum pose age 0.5 s |
| `pulse_seconds`, `pause_seconds` | Default 0.12 s motion, 0.3 s stopped |
| `ble_device` | WALL-Y name, or identifier returned by Bleak on this laptop |
| `ble_characteristic` | `abcdefab-1234-5678-1234-abcdefabcdef` from the working script |
| `ble_write_response` | True: acknowledged writes supported by supplied firmware |

Stop bypasses throttling. Normal writes happen only on changes or refreshes.
Pulses reduce average travel, **not motor speed**: F/L/R still operate at the
firmware's full speed. No PWM, PID, path planning or obstacle avoidance is added.

Image headings: 0 right, 90 down, 180 left, 270 up. Positive error selects R by
default. Red arrows show marker heading; yellow arrows in phases 2–4 include the
mounting offset. Point the robot nose image-right and adjust the offset until
yellow points right too. Keep the camera fixed, without mirrored previews.

Before autonomous motion, use `.venv/bin/python ble_control.py` for a brief R
followed by S while observing WALL-Y. R should increase corrected heading
(clockwise). If it decreases it, set `invert_turns` to true. Repeat for L, then
verify phase 3 again. The firmware comments/electrical pin values do not prove
the physical turn sign; it must be measured on the assembled robot.

The manual script preserves the supplied behavior, including H. The Arduino
sketch is copied unchanged to `firmware/wall_y/wall_y.ino`. Its service UUID is
`12345678-1234-1234-1234-1234567890ab`.

Tests use generated ArUco frames and mocked BLE/UI; physical turning, camera
latency and stopping distance still require the staged hardware checks above.
BLE reference: [Bleak client](https://bleak.readthedocs.io/en/latest/api/client.html).

## Two robots on one camera

Use `--robots-config navigation_robots.json` to enable independent WALL-Y/Eeva
control. Existing commands without this option still run the single-robot mode.
The profiles use unique advertised names and `response=False` writes:

- WALL-Y (`robot-a`): `WALL-Y`
- Eeva (`robot-b`): `Eeva`

Phase 4 starts the camera immediately and keeps its window responsive while it
performs one 10-second BLE scan. The window reports that the robots are
connecting and remain stopped. Startup resolves both names to the current Mac's
`BLEDevice` objects and then connects sequentially. This avoids storing
machine-specific macOS UUIDs and avoids Bleak's implicit per-client discovery.

**Before driving**, set each profile's actual `marker_id`, calibrated
`heading_offset_degrees`, and `invert_turns`. The sample assumes IDs 0 and 1 and
zero offsets; it does not import calibration from the single-robot file. Each
profile accepts all the existing navigation settings (thresholds, pulses, etc.).
Duplicate marker IDs or BLE devices are rejected.

```sh
python -m app.navigation --camera 1 --phase 1 --robots-config navigation_robots.json
python -m app.navigation --camera 1 --phase 2 --robots-config navigation_robots.json
python -m app.navigation --camera 1 --phase 3 --robots-config navigation_robots.json
python -m app.navigation --camera 1 --phase 4 --robots-config navigation_robots.json
```

Verify both identities/headings in phases 1–3. In the **camera window**, press
**W** for WALL-Y or **E** for Eeva, then click that robot's target. Magenta marks
WALL-Y's target and cyan marks Eeva's. Both start without targets and stopped.
Press **A** to arm only the selected robot. Select the other robot, click its
target, and press A again to run both. Switching selection does not stop the
other robot. Clicking a new target disarms only the selected robot.

SPACE stops/disarms **both**, and Q/window close/error stops and disconnects both.
Arrival and marker loss stop only the affected robot; stale camera frames affect
both. Neither resumes after a timeout without A. Any BLE disconnect/write failure
ends the entire session and attempts stop/cleanup on both connections. If the
second connection fails, the first is also stopped and disconnected. Restart to
reconnect. No automatic re-arming occurs.

Device identifiers differ between Macs, so the checked-in fleet configuration
uses `ble_direct_address: false` and each robot's exact, unique advertised name.
If a robot is not found, verify that it is powered, advertising under that name,
and disconnected from other controllers. Direct-address mode remains available
for diagnostics, but a configured identifier must belong to the current Mac.

This is simultaneous independent point-to-point driving, **not collision
avoidance**. Use clear, separated paths. It remains separate from backend task
execution, game autonomy and backend stop controls; use this window's SPACE/Q.
Physical two-robot behavior must be tested on the camera laptop; automated tests
use mocked BLE and UI and do not move robots.

## Calibrated traffic control and detours

Add `--traffic-config traffic_config.json` to the **fleet** command to enable
traffic protection. The old commands above retain independent driving for
compatibility; they do not enable this protection implicitly.

1. Keep the camera fixed and verify both marker IDs, corrected headings and turn
   directions. In `backend/traffic_config.json`, set the actual image resolution.
2. Set `arena` to the usable rectangle `[left, top, right, bottom]` in camera
   pixels. It must align with the backend map when using backend tasks (map origin
   upper-left, x right, y down). This simple mapping assumes a perpendicular,
   unmirrored camera with a rectangular arena; it does not correct perspective.
3. Set each `radii` value to the distance from its marker center to its furthest
   chassis corner, including attachments. It must cover the complete turning
   sweep, not just the ArUco square. Set `margin` for localization error and
   measured stopping clearance. List fixed obstacles as pixel rectangles.
4. Measure an upper bound on actual full-command speed in **pixels/second** for
   `max_speed`. `stop_latency` covers localization delay, BLE stop delivery and
   coasting (minimum 1 second). The forward guard checks that entire travel
   envelope plus the next pulse. Increase the bound for slow camera/network
   conditions; don't lower it just to force a route through a gap.
5. Only after these measurements, set `calibrated: true`. The supplied values are
   examples; false or a changed frame resolution blocks all motion.

From `backend`, first inspect dry-run routes:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m app.navigation --camera 1 --phase 3 --robots-config navigation_robots.json --traffic-config traffic_config.json
```

Use W/E and click separate targets. Red circles include chassis + margin; green
lines show the checked detour. The displayed/logged selected commands include
traffic overrides. No BLE connection happens in phase 3. Then use the same
command with `--phase 4`. A arms the selected robot; arm both to queue both trips.
SPACE disarms both. Missing either marker, insufficient clearance, failed route,
wrong resolution or BLE failure stops both. Re-arm with A after resolving it.

Only one robot moves at a time. The other holds its position while a small bounded
camera-grid search finds a route around its footprint and configured obstacles.
Every segment and the actual forward-heading stopping envelope are checked.
There is a settling delay before handing movement to the other robot. Priority
alternates when possible; an impossible route may let the other robot go first.
Occupied destinations and tight/unmodeled spaces require repositioning. This is
not contact sensing: actual bumps cannot be diagnosed without extra hardware.
No LLM response authorizes movement. Do not run a second BLE/manual controller
alongside navigation.

## Hardware backend and spectator traffic conversation

Start the backend with `GAME_MODE=hardware` (simulation remains available for
other demos). For example, in a separate terminal in `backend`:

```sh
GAME_MODE=hardware AUTONOMY_ENABLED=true AUTONOMY_PROVIDER=mock .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Use `AUTONOMY_PROVIDER=gemini` and your existing local key/model settings for real
Gemini planning. Point the frontend at this same backend as described in the
backend README. Then on the camera/BLE laptop:

```sh
.venv/bin/python -m app.navigation --camera 1 --phase 4 --robots-config navigation_robots.json --traffic-config traffic_config.json --backend-url http://127.0.0.1:8000
```

Replace the URL with the backend laptop's LAN URL when it runs elsewhere. Start
the game in the UI, wait for fresh telemetry, and press **A** in the camera window
to enable following backend tasks for both robots. New tasks can then run until
SPACE, a safety fault, stale backend (>0.75s), game stop/reset, or remote stop
revokes permission. A is required again after interruptions. Click targets are
disabled in backend mode. Task cancellation clears its target.

The bridge publishes real pose/health/blocked state and reports arrival once per
matching task/session. Backend activity timers and transactions remain responsible
for inventory/coins. Map location points must lie in free, reachable camera space.
Routes use the whole arena; location labels/zones are not obstacles themselves.

Traffic reservations publish a short deterministic exchange in the existing
spectator chat, e.g. “I'll take the clear route around you. Hold there a moment.” /
“You've got it. I'll wait until you're clear, then take my turn.” Messages describe
the controller's decision; Gemini is not negotiating motor safety. Without
`--backend-url`, reservations appear only in the local overlay/log.

## Optional ESP32 command-expiry firmware

`firmware/wall_y/wall_y.ino` remains unchanged. The new
`firmware/wall_y_watchdog/wall_y_watchdog.ino` preserves the BLE UUIDs, commands and
motor mapping, and stops after 500 ms without F/B/L/R. S, disconnect and boot also
stop; H never extends motion. Motor callbacks/watchdog share a mutex. Set the
variant's `DEVICE_NAME` to `Eeva` for that robot and verify its actual motor pins
before uploading. Existing navigation refreshes every 300 ms; keep refresh below
500 ms. Manual F now expires unless repeated. Flash this variant before testing
traffic movement so a frozen laptop cannot leave a connected robot driving.
The sketch still needs compilation/upload with your installed ESP32 Arduino core;
it cannot be flashed or physically verified from this development laptop.

## Draw buildings before the game

On the camera laptop, stop navigation and any other robot controller first, then
run from `backend`:

```sh
.venv/bin/python -m app.navigation.calibrate --camera 1 --config traffic_config.json
```

This setup tool opens only the camera; it never connects to BLE or starts a game.
When the image settles, press **SPACE** to freeze it for editing:

- **A**: drag the usable arena rectangle.
- **B**: drag a box around each building. Include walls, roofs/overhangs and every
  part the robot could hit. Mark its full occupied footprint, not just a doorway.
- **W / E**: drag a tight box around the entire corresponding robot (including
  wheels/attachments), then click its ArUco marker's **center**. This computes
  the largest marker-to-box-corner distance as its turning radius in pixels.
- **U**: remove the last building box; repeat to redraw older boxes.
- **S**: save into the existing traffic JSON. **Q** closes; unsaved edits are lost.
  Selecting another mode cancels an unfinished box/marker selection.

The robots are **6.2 × 5.2 inches**: with a centered marker their minimum turning
radius is `hypot(6.2, 5.2) / 2 ≈ 4.05 inches`. The camera measurement avoids guessing
pixels per inch and also handles an off-center marker conservatively. If the
robot is rotated, its axis-aligned box may yield a larger, conservative radius.
The blue circle shows that radius; the red circle adds the configured margin.
Building boxes automatically get that same radius + margin in the planner;
you do not need to manually enlarge them for the robot's width.

Saving keeps speed, latency and other control settings, but sets
`calibrated: false` so changed geometry must be reviewed before movement. Check
both radii, margin and measured speed/stop settings, then set `calibrated: true`
and run phase 3 before phase 4 as above. A changed image resolution clears old
building/arena boxes; remeasure both robots as well. If the camera moves or zoom
changes, rerun setup even if resolution is unchanged. Buildings moved during a
game require stopping navigation and updating this static map.
