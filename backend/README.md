# Backend

The Python backend uses FastAPI and Pydantic for HTTP, WebSocket updates, and API models.
`GET /world`, live `/events` snapshots, game start, simulated `MOVE_TO`, `HARVEST`, `FISH`, `BUY`, and `SELL` tasks, spectator agent chat, and standalone overhead vision are implemented. Hardware navigation and robot communication remain placeholders.

- `app/main.py`: application composition and background-work lifecycle.
- `app/config.py`: runtime settings and hardware configuration.
- `app/schemas.py`: validated canonical world snapshot models.
- `app/state.py`: authoritative in-memory world state and immutable snapshots.
- `app/api/`: `GET /world`, spectator agent chat, and planned game APIs.
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

Vision is implemented independently of the game server. Requires Python 3.10+.
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

## Per-robot agent orchestration

Each robot gets an independent Google ADK `LlmAgent` and runner using Gemini.
The default model is `gemini-3.5-flash-lite`; set `AGENT_MODEL` to change it.
Agents choose one high-level task and a short public reason. They never control
motors, assign rewards, or change game state themselves.

Install the updated `requirements.txt`, then run one offline planning round:

```sh
python -m app.agents --provider mock
```

This explicit mock policy proposes harvesting for Billy and fishing for Milo.
It accepts tasks into a temporary in-memory demo snapshot only; it does not run
movement, harvest timers, or the frontend simulation. Output is labeled `dry_run`.
No API key or network access is used in mock mode.

For real Gemini decisions, set `GOOGLE_API_KEY` in your shell to an AI Studio API
key, set `GOOGLE_GENAI_USE_VERTEXAI=FALSE`, and run:

```sh
python -m app.agents --provider gemini
```

That makes real model calls but still uses the demo task sink, with no hardware
or backend calls. `--world /path/to/world.json` accepts a world snapshot instead;
the file is never modified. The game must be `RUNNING`, below its gold goal, with
idle, online, unblocked, unstopped robots whose tracking is `TRACKED` and pose is
known. Otherwise planning is skipped. Missing credentials, invalid decisions,
and model failures do not silently switch to the mock policy.

`backend/.env.example` lists configuration; the CLI reads exported environment
variables, not `.env` automatically. Defaults: `AGENT_INTERVAL_SECONDS=10` between
attempts per robot, `AGENT_TIMEOUT_SECONDS=20` per model call or submission. Each decision uses
one bounded model call, the current structured world, and no camera frames or
conversation history. Temporary ADK sessions are deleted after each decision.

Responsibilities:

- `app/agents/planner.py`: structured decisions, availability/trade checks, mock policy.
- `app/agents/gemini.py`: independent ADK agents, bounded JSON model responses.
- `app/agents/orchestrator.py`: scheduling, latest-state revalidation, task submission.
- `app/agents/__main__.py`: standalone dry-run demonstration.

For backend integration, keep one `AgentOrchestrator` for the game process and call
`await orchestrator.tick(read_world, submit_task)` from the backend lifecycle.
`read_world()` returns the current authoritative snapshot. Async
`submit_task(session_id, request)` must atomically revalidate through the same
service used by manual tasks, handle request-ID idempotency, reject old sessions,
and return `True` only after the accepted task is visible in the snapshot.
The request follows `api.md`; the host should publish an `agent_decision` event
from accepted outcomes. WAIT is internal and never submitted as an API task.

The scheduler runs agents sequentially so each sees its teammate's newly accepted
tasks. Overlapping ticks are skipped; busy robots never trigger model calls.
Planning errors are isolated per robot and retried only after the cooldown.
An uncertain submission blocks further planning for that robot until the host
reconciles the request ID and calls `reconcile(session_id, robot_id)`, or a new
game session starts. Stop/reset during planning is checked before submission.
Trade checks here are preflight only; the task service must recheck funds, stock,
and inventory atomically at execution. The host owns freshness thresholds and
must mark stale camera poses as `STALE` before allowing physical tasks.

The frontend now reads the authoritative backend world and submits movement and
collection tasks to the shared task service. Its local simulation remains an
offline fallback. The standalone agent orchestrator is not yet hosted by the game
process; the browser chat preview currently dispatches supported proposals.
Authoritative trade prices always come from `world.market.items`.

Run agent tests (mocked model responses; no billable calls):

```sh
python -m unittest discover -s tests -p 'test_agents.py' -v
```

References: [Google ADK](https://google.github.io/adk-docs/agents/llm-agents/) and
[Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).

## Live spectator conversation

Run the chat API from `backend` in a terminal with your exported Gemini API key:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in a second terminal using its README instructions. In the
**Robot conversation** panel, choose **Mock demo** or **Gemini agents**, then
**Start chat**. Pause stops future rounds; an in-flight round may finish. Gemini
mode makes paid/quota-counted calls; mock mode is explicitly scripted. No model
calls happen until a browser starts the conversation. The key stays on the backend.

Each round sends the current frontend world snapshot to the local backend.
Every available robot proposes one action and a brief public `message` to its
teammates. The second robot receives the first robot's message before answering;
the next round includes the recent conversation, so both robots can respond.
These are intentional public coordination messages, not private model reasoning.
They appear over WebSocket within roughly half a second of each model response.

The chat service itself is a **discussion-only preview**, but the frontend dispatches
new proposals while chat is enabled. `MOVE_TO`, `HARVEST`, `FISH`, `BUY`, and
`SELL` therefore use the authoritative backend task service.
READY and RUNNING games may discuss; stopped, completed, busy, offline, or untracked
robots are skipped. The standalone `AgentOrchestrator` is not yet hosted by the game
process.

The service keeps one shared conversation in memory, with at most 100 messages;
only the latest 20 are sent to models. A new game session or provider switch clears
the history. Restarting the backend clears it too. One browser should operate the
Start/Pause controls; other browsers can watch the same live feed without starting
another loop. Concurrent rounds are rejected, and the default 10-second cooldown
is enforced server-side. Browser rounds wait at least 12 seconds after completion.
Model errors pause that browser's loop and display a redacted error, without
fabricating chat messages. Reconnecting viewers receive the latest full history.

Configuration:

- Backend `FRONTEND_ORIGINS`: comma-separated allowed browser origins; defaults to
  `http://localhost:5173,http://127.0.0.1:5173`.
- Frontend `VITE_API_BASE_URL`: backend URL; defaults to `http://localhost:8000`.
- Existing `GOOGLE_API_KEY`, `AGENT_MODEL`, `AGENT_TIMEOUT_SECONDS`, and
  `AGENT_INTERVAL_SECONDS` still apply. Restart the server after changing them.

Transport and payloads are documented in `api.md`. The implementation lives in
`app/agents/chat.py`, `app/api/agent_chat.py`, and `app/main.py`; it uses the existing
per-robot Gemini planner. The game `/world` and `/events` endpoints provide the
authoritative frontend state.

For the discussion preview only, the frontend's buy-only market catalog is
augmented with inventory sale items/prices in a copied snapshot. This lets agents
understand the current dashboard without changing its data. This adapter is never
used by authoritative task validation or real transaction execution.
