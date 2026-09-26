# Backend

The Python backend, using FastAPI and Pydantic for HTTP, WebSocket updates, and API models.
Most server files are commented placeholders. Standalone overhead vision is implemented; see below.

- `app/main.py`: application composition and background-work lifecycle.
- `app/config.py`: runtime settings and hardware configuration.
- `app/schemas.py`: shared request, response, and event models.
- `app/state.py`: authoritative world state and consistent snapshots.
- `app/api/`: HTTP routes, WebSocket snapshots, and error formatting.
- `app/game/`: session controls, task lifecycle, and market transactions.
- `app/agents/`: high-level task decisions through the same validation as manual requests.
- `app/vision/`: overhead camera localization and coordinate calibration.
- `app/navigation/`: deterministic movement, arrival detection, and stop handling.
- `app/robots/`: ESP32 communication and robot health reporting.
- `app/simulation/`: simulated movement and telemetry for development without hardware.

## How the pieces connect

The API and agents submit work to game logic. Game logic owns state changes, timers, and rewards, and requests movement from navigation. Vision supplies poses; navigation sends motor commands through the robot client. Simulation substitutes movement and telemetry while keeping the same game logic and frontend contract.

Start with modules in one backend process; separate processes only when integration needs justify it. Keep hardware I/O out of API handlers and game rules. Implement synchronization around shared state and transactions when adding concurrent work.

[api.md](../api.md) remains the shared interface contract. Implement schemas and snapshots first, then tasks with simulation, hardware integration, and autonomous decisions. Choose the agent provider, camera library, and robot transport when those modules are implemented. ESP32 firmware will need its own project once its toolchain is selected; the onboard motor watchdog belongs in that firmware.

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
