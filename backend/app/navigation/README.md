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
