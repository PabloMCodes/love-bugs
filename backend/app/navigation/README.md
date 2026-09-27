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
requires A plus fresh tracking again. The supplied firmware stops on detected
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
