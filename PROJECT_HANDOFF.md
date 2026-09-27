# Love Bugs: project and Codex handoff

Prepared 2026-09-27. Implementation baseline: **main at `2da2936`**, before this
handoff-only commit. Teammate camera runbook `4a218a1` was incorporated during
final synchronization; it changes documentation only. Remote branch comparison: **origin/gameLogic at `6eb14fc`**.
This is a point-in-time implementation and verification record. Recheck branches
before acting on it; do not assume later teammates' commits are described here.

## 1. Read this first

The project has a working backend-authoritative game, simulation, separate
per-robot agents, spectator conversation, camera localization, BLE control of two
physical robots, and a recently added guarded navigation/backend bridge.

**The end-to-end physical demo is not yet verified.** The owner reported successful
phone-camera input and unguarded phase-4 control of both robots. Subsequent logs
showed two different issues: the camera laptop initially ran old code with traffic
protection OFF, and then ran with protection ON but `calibrated: false`, causing
STOP commands only. There is not yet evidence of a complete successful physical
route around the configured buildings, followed by actual task rewards and sales.

**Important branch distinction:** main does not yet contain the teammate's newer
planting/crop/cooperative-economy/tiered-fishing work on `gameLogic`. Do not
reimplement those features without inspecting that branch. This handoff does not
merge or rewrite their work. All of this conversation's implementation commits
listed below are already on main.

**Database status:** local persistence and HTTP/WebSocket verification passed.
Tiger Data connection testing was explicitly requested, but a usable connection
URL/local environment file has not been provided to this Codex environment. Live
Tiger success must not be claimed. No credentials belong in this handoff or Git.

## 2. Product goal and scope

The intended experience is a small cooperative indie-style farming/fishing game:
WALL-Y and Eeva autonomously choose useful work, travel through a physical arena,
collect and sell resources, and communicate in a chat spectators can watch.
Separate wallets and inventories contribute to shared progression and victory.

Two levels of scope should remain explicit:

| Scope | Meaning |
| --- | --- |
| Minimum complete demo | One reliable collect → travel → sell → gold → victory loop, first simulated and then physical, with visible task state/chat and working stops. |
| Expanded product direction | Three crop stages, planting/growth, variable fishing, money transfers/requests, cooperative unlocks, evolving presentation. Much of this now exists on the teammate's branch, not main. |

Use [GAME_DESIGN.md](GAME_DESIGN.md) for product intent,
[GAME_PLAN.md](GAME_PLAN.md) for the milestone plan, and [api.md](api.md) for shared
contracts. Some roadmap checkboxes and older README paragraphs lag implementation;
this document calls out the important discrepancies rather than silently treating
plans as shipped features. For the camera laptop, also read the teammate
[CAMERA_SETUP_GUIDE.md](CAMERA_SETUP_GUIDE.md), including its operational checklists
and cross-Codex audit prompts.

Keep the hackathon priorities: working end-to-end behavior, reliability,
integration, sponsor requirements, then polish. Do not add ROS, Docker, SLAM,
a general robotics framework, or another source of game truth for this milestone.

## 3. Architecture and ownership

```text
Frontend dashboard ← HTTP /world + WebSocket /events ← authoritative WorldStore
       ↑                                                    ↑
       └── spectator chat feed ← AgentChat ← accepted agent decisions
                                      ↑                    ↑
                              local traffic messages   mock/Gemini planners
                                                           ↓
                                              validated high-level tasks
                                                           ↓
                  simulation mode: SimulationRunner generates movement/arrival
                  hardware mode: camera laptop reads tasks through BackendBridge
                                                           ↓
Camera → ArUco pose → TaskFollower / clicked target → traffic + steering guard
                                                           ↓
                                                rate-limited BLE F/L/R/S
                                                           ↓
                                                    ESP32 motors
                                                           ↓
                  physical poses/health/arrivals → backend activity/reward rules
                                                           ↓
                                   atomic SQLite or Tiger Data history recording
```

- Backend rules own task acceptance, inventory, gold, market effects, stages and
  goal completion. Neither a chat sentence nor a BLE command awards currency.
- Each robot has its own planning context. A shared deterministic orchestrator
  schedules decisions, checks current state and submits valid tasks.
- Python navigation owns motor selection, localization freshness and clearance.
  Gemini never directly decides F/L/R/S or overrides the traffic guard.
- The camera laptop is the hardware telemetry/BLE owner. Do not run a second
  manual BLE controller or competing pose/health publisher at the same time.
- The frontend renders live state. Its local fallback can look convincing when
  the backend is unavailable: confirm the connection source and session before
  using a UI change as evidence of a real backend or physical transaction.
- The persistence recorder runs before publishing accepted state in memory. A
  failed required write rejects the transition; it does not award an unrecorded
  reward or silently switch databases.

## 4. Current status by subsystem

| Subsystem | Main implementation | Evidence and remaining limits |
| --- | --- | --- |
| Backend world/tasks/economy | Implemented | Automated simulation, lifecycle and economy checks pass. Main has MOVE_TO, RETURN_HOME, HARVEST, FISH, BUY, SELL. |
| Mock and Gemini agents | Implemented | User previously received valid live Gemini decisions with `gemini-3.5-flash-lite`; current tests mock model calls. No claim of a new live Gemini test. |
| Spectator chat and banter | Implemented | Backend-owned decisions, bounded conversation, paired occasional banter. Chat itself does not execute movement. |
| Frontend dashboard | Implemented baseline | Backend state, market, controls, robot panels and chat; dedicated victory presentation remains a polish gap. More UI work exists on gameLogic. |
| ArUco/camera | Implemented | Owner reported successful iPhone camera feed; generated-image tests cover detection. |
| Two-robot BLE control | Implemented | Owner reported both working in phase 4 before guarded routes were verified. |
| Arena/building editor | Implemented | Owner reported setup worked; editor writes pixel rectangles and measured robot radii. |
| Guarded routes/right-of-way | Implemented, physical validation pending | Unit/UI tests cover collision checks and default guard loading. Latest reported live run stopped on unreviewed calibration. |
| Hardware task bridge | Implemented, physical game verification pending | Tests cover authority loss, stop/reset/cancellation, telemetry, arrivals and chat transport. |
| ESP32 expiry watchdog variant | Code added, deployment unconfirmed | Original sketch preserved; variant was not compiled/uploaded or physically tested here. |
| SQLite persistence/setup | Implemented and locally verified | State/events/positions, transactions, history, setup commands, economy persistence checks. |
| Tiger Data | Adapter and isolated-schema test implemented | Live URL unavailable here; the hosted integration test remains unrun. |
| Crop lifecycle/cooperative economy/tiered fish | Teammate branch only at snapshot time | Review/merge gameLogic rather than duplicating it. Its branch tests were not run in this handoff. |

## 5. Repository map: where to work

| Files/directories | Responsibility |
| --- | --- |
| `backend/app/config.py` | Environment settings, vision configuration, navigation profiles and validation. |
| `backend/app/main.py` | FastAPI composition, persistence initialization, simulation/activity loop, autonomy and telemetry watchdog lifecycle. |
| `backend/app/state.py`, `schemas.py` | Canonical world, atomic validated transitions and shared payload types. |
| `backend/app/game/` | Main-branch market/activity/session rules. |
| `backend/app/simulation/simulator.py` | Simulated movement; backend activities also progress in hardware mode after arrival. |
| `backend/app/api/routes.py`, `events.py`, `history.py` | World/task/lifecycle/robotics API, live snapshots, historical reads. |
| `backend/app/agents/planner.py` | Decision schema, deterministic mock choices and validation. |
| `backend/app/agents/gemini.py` | ADK/Gemini adapter, prompts and structured decision handling. |
| `backend/app/agents/orchestrator.py`, `runtime.py` | Scheduling, fresh-state checks and backend task submission. |
| `backend/app/agents/chat.py`, `banter.py` | Bounded conversation, repetition suppression and low-priority paired banter. |
| `backend/app/api/agent_chat.py` | Chat HTTP/WebSocket transport and deterministic traffic exchanges. |
| `backend/app/vision/capture.py`, `localization.py`, `__main__.py` | Configurable input, ArUco poses/zones and standalone debug viewer. |
| `backend/app/navigation/controller.py` | Image-space steering and latched pulse/arming gate. |
| `backend/app/navigation/fleet.py`, `__main__.py` | Camera/UI loop, robot selection, targets, BLE startup and traffic integration. |
| `backend/app/navigation/traffic.py` | Footprints, arena/obstacle checks, right-of-way, bounded grid detours and stopping envelope. |
| `backend/app/navigation/calibrate.py` | Frozen-camera setup editor for arena, buildings and robot footprints. |
| `backend/app/navigation/backend.py` | Async HTTP bridge and locally armed task follower. |
| `backend/app/robots/client.py` | Existing Bleak transport, command throttling, timeouts and cleanup. |
| `backend/app/robots/watchdog.py` | Backend telemetry freshness watchdog; distinct from the ESP32 motor watchdog. |
| `backend/app/persistence/` | Transactional store, recorder, history models, init/check CLI. |
| `backend/vision_config.json` | Standalone marker mappings and normalized named zones. |
| `backend/navigation_robots.json` | WALL-Y/Eeva IDs, marker IDs, heading offsets, turn inversion and BLE settings. |
| `backend/navigation_config.json` | Original single-robot bring-up settings; not fleet calibration. |
| `backend/traffic_config.json` | Pixel arena/buildings/radii and movement-envelope settings. Checked-in examples are NOT calibrated to the real arena. |
| `firmware/wall_y/wall_y.ino` | Original supplied firmware, retained unchanged. |
| `firmware/wall_y_watchdog/wall_y_watchdog.ino` | Separate command-expiry variant. |
| `backend/ble_control.py` | Archived manual single-robot BLE control; no camera boundary protection. |
| `frontend/src/hooks/useWorld.js`, `src/api/` | Backend connection, snapshots, session/revision handling and local demo fallback. |
| `frontend/src/components/` | Dashboard, game controls, market, map, robot status and spectator chat. |
| `backend/tests/` | Unit/integration tests, simulated BLE/camera checks and real localhost HTTP smoke test. |

## 6. Work completed in this conversation and relevant history

These commits are useful anchors for another Codex. They are not an exhaustive
list of teammates' styling/gameplay commits. Inspect `git show <hash>` for exact
diffs instead of guessing which contributor implemented a neighboring feature.

| Commit | Work |
| --- | --- |
| `c8693fc` | Standalone overhead ArUco tracking. |
| `fc5ff37`, `1b085ee`, `b42d5c0`, `0c6b0b6` | Gemini structured-output compatibility, useful redacted API errors, unsupported schema property fix and model default update. |
| `74b1267` | Incremental ArUco + BLE click-to-drive navigation, phased verification. |
| `01acdc0`, `42fbdff`, `841e8f5` | Inventory-aware agent sales, backend-owned autonomy and spectator-only chat. |
| `02490f7` | Independent two-robot BLE navigation using one camera. |
| `1fcb354`, `12e9db6` | Grounded/nonrepetitive dialogue and occasional paired banter. |
| `5a91300`, `ba1e1cc`, `487e4fb` | BLE timeout/error reporting, one fleet discovery scan, responsive camera UI during connection. |
| `763805c` | Teammate CAD/3D-print additions retained on main. |
| `cca4eef` | Fleet traffic controller, checked detours, backend task/telemetry bridge, traffic chat, separate watchdog firmware. |
| `84a3962` | Building-box and robot-footprint editor, tests and instructions. |
| `f34c4ee` | Saved traffic bounds mandatory by default in fleet mode; single-robot CLI phase 4 rejected; regression tests. |
| `2da2936` | Database init/check CLI, dotenv support, SQLite setup fixes, Timescale minimum-version checks and expanded persistence verification. |
| `4a218a1` | Teammate camera/localization/navigation/traffic runbook, preserved during this handoff sync. |

All implementation changes above were committed and pushed before this handoff.
The handoff adds documentation and a root README link, not another game/control
implementation or an automatic merge of remote feature branches.

## 7. Localization, coordinate systems and physical facts

The owner supplied robot dimensions of **6.2 × 5.2 inches**. With a centered
marker, the minimum radius covering the rectangular chassis during rotation is
`hypot(6.2, 5.2) / 2 ≈ 4.05 inches`, before attachments and clearance. An off-center
marker needs the maximum distance from marker center to any chassis corner.

Do not mix these coordinate systems:

| Data | Coordinates |
| --- | --- |
| Standalone vision normalized x/y and zone rectangles | 0–1 fractions of the camera frame. |
| Navigation targets, arena, buildings, footprint radii, stop distance | Camera image pixels. |
| Backend map/pose/locations | World units bounded by map width/height (main default 100 × 100). |

The hardware bridge maps the calibrated arena rectangle linearly to backend map
width/height. It assumes an overhead, unmirrored, suitably aligned camera. No
perspective homography, lens correction, or automatic relocation of buildings is
implemented. Camera movement/zoom invalidates calibration even when resolution
stays unchanged. Different robot/roof heights can affect projected footprints;
check against the real floor geometry and leave suitable margin. The requested
iPhone 0.5×/ultrawide selection has not been implemented or verified here; camera
index selection is not a zoom setting. Recalibrate after any lens/zoom change.

ArUco uses OpenCV contrib's **DICT_4X4_50**. It detects multiple markers, extracts
pixel centers, normalized coordinates and image headings, and draws outlines,
centers/arrows/labels. Image heading is clockwise: 0° right, 90° down. Each robot's
`heading_offset_degrees` aligns the detected marker with its actual nose;
`invert_turns` corrects the experimentally measured turn sign.

The named zones `homebase`, `farm`, `lake`, `market` are not building obstacles.
Standalone zone-change events avoid emitting the same occupancy every frame.
The physical task destination comes from backend map location points, not from
assuming that the center of every visual building is a reachable destination.
Place service/arrival points in open space beside buildings.

## 8. BLE, safety and traffic semantics

- Stable IDs are `robot-a` (WALL-Y) and `robot-b` (Eeva). Default marker IDs are 0/1;
  verify the actual printed markers on the camera laptop.
- Default discovery uses exact advertised names, one scan for both devices,
  then sequential connection to resolved BLEDevice objects. macOS device UUIDs
  differ across laptops; do not copy one laptop's addresses as universal IDs.
- The shared writable characteristic is `abcdefab-1234-5678-1234-abcdefabcdef`.
  Fleet profiles use `response=False`, matching the owner's working controller.
- Motor commands are F/B/L/R/S. The navigation selector uses F/L/R/S. H in the
  original firmware prints a health message to serial; it is not a rich telemetry
  characteristic or a proof of motor execution.
- Normal command rate is bounded, with change/refresh handling. STOP can bypass
  the normal movement rate limit. Defaults include 10 Hz, 0.3-second refresh,
  0.12-second movement pulses and 0.3-second pauses.
- Clicking a target disarms that robot. A is explicit arming; SPACE stops/disarms
  both. Q/window close attempts STOP and disconnects. A lost BLE link/write fault
  ends the session with cleanup attempts for both robots.
- Missing either marker blocks fleet traffic and disarms both. Fresh frames and
  both robot footprints are required. This is intentionally conservative.
- Traffic uses circles covering each robot's full turning sweep, static building
  rectangles expanded by radius + margin, and an arena inset by that clearance.
- Forward movement is also checked along the **actual corrected heading** over
  the configured speed/latency/pulse stopping envelope. Do not lower these bounds
  simply to make a rejected route pass.
- Only one robot moves at a time. Priority can alternate; the waiting robot is a
  stationary obstacle. Routes use a small bounded grid search and checked segments.
  There is a settling delay before the next reservation moves.
- A target occupied by the other robot, no clear path, a tight gap, or a predicted
  unsafe pulse causes STOP. There is no automatic contact recovery, reverse escape,
  arbitrary deadlock solver, or dynamic unseen-obstacle perception.
- “I'll go first / I'll wait” chat describes the controller's reservation. It is
  deterministic narration, not a slow LLM safety negotiation. The mover may detour
  around the waiting robot; later the waiting robot gets a checked route in turn.
- Without a bumper/force sensor, the system cannot reliably identify a physical
  collision as a bump. Preventive clearance checks are not a contact detector.

Original ESP32 firmware stops on boot/connect/disconnect but has no connected-link
command-expiry stop. The separate watchdog variant stops after 500 ms without a
motion command; H does not renew it. Verify motor pins and device name for each
robot, compile with the team's actual Arduino/ESP32 core, flash, then test expiry
and disconnect behavior. Deployment of this variant is **not confirmed** here.

## 9. Latest camera-laptop troubleshooting evidence

The logs explain why earlier tests did not demonstrate building avoidance:

1. The command omitted `--traffic-config` on an older checkout and printed
   `Traffic protection OFF`. It ignored the saved geometry by design at that time.
2. Main commit `f34c4ee` removed that fleet bypass. The default config path is
   shared with the setup editor; startup reports the resolved path/building count.
3. A later run explicitly included the flag and printed
   `TRAFFIC: Calibrate traffic_config.json before movement`. Both BLE streams sent
   S. This means the guard was active but calibration was unreviewed, not that
   movement was being safely tested or that BLE had failed.

The editor deliberately saves `calibrated: false`. Verify geometry, both radii,
measured speed and stopping margin, set true, then inspect phase 3 before phase 4.
Do not replace the camera laptop's custom JSON with the checked-in example. Do
not reset/stash-discard its calibration to get a Git pull to succeed.

## 10. Agent and conversation behavior

- Use mock autonomy for a deterministic rehearsal; Gemini is optional high-level
  planning over the same validated task contract.
- `AGENT_MODEL` currently defaults to `gemini-3.5-flash-lite`, based on a successful
  user run after the earlier model was unavailable to that account. Future model
  availability/cost must be checked at the time of any change.
- `python -m app.agents --provider gemini` is a planning/dry-run diagnostic. An
  accepted dry-run request does not move a robot or increase gold by itself.
- Continuous execution is hosted by FastAPI with `AUTONOMY_ENABLED=true`, an
  appropriate provider, and game status RUNNING. The browser is not the scheduler.
- Decisions use current world state and recent dialogue. Repeated near-identical
  messages are suppressed; accepted task execution still matters even if silent.
- Banter is occasional, paired and lower priority than useful task communication:
  current defaults allow an opener after 12 quiet seconds, exchanges no more often
  than roughly 35 seconds, and a reply after about 4 seconds plus model latency.
  These are scheduling defaults, not a guaranteed uninterrupted speech cadence.
- Chat keeps a bounded in-memory feed. It is not a database-backed transcript,
  a record of raw private model reasoning, or proof that a task completed.
- On main, `frontend/src/components/AgentChat.jsx` is spectator-only. Older
  frontend README paragraphs describing browser “Start chat” dispatch are stale.
  Do not restore browser-owned execution just to match those paragraphs.

## 11. Persistence: what is complete and what is pending

The main backend stores one transaction containing the accepted snapshot, newly
emitted events and changed poses. It preserves the established gameplay/API
contracts rather than restoring the older separate cooperation demo.

| Table | Purpose |
| --- | --- |
| `world_state` | Latest snapshot per session, including tasks, gold, inventory, market and goal. |
| `robot_events` | Historical accepted events/outcomes; Timescale hypertable on PostgreSQL. |
| `robot_positions` | Historical changed pose observations; Timescale hypertable on PostgreSQL. |
| `event_ids` | Session-wide event identity protection. |
| `event_order` | Revision and ordinal ordering for events with matching timestamps. |

SQLite is the local default. `DATABASE_URL` selects PostgreSQL/TimescaleDB and
must not silently fall back to SQLite on failure. Startup/setup requires
TimescaleDB 2.13+ for the current generalized hypertable API and appropriate
schema/table permissions. `init` creates/migrates tables idempotently; `check` is
read-only and reports the backend/schema/hypertable readiness without credentials.

Every new backend process starts a new live session. Older sessions remain
queryable; there is no exact full-state replay, restart resume, chat transcript
archive, or configured history-retention policy. Do not promise those features.
Use `GET /events?session_id=...` and `GET /robots/{id}/history?session_id=...` for
bounded history, keeping their documented response formats.

The requested live Tiger test remains blocked on a locally supplied URL. The
integration test uses a randomly named `smoke_...` schema and cleans up only that
schema. It now exercises initialization, hypertables, actual collection/sales,
coin/inventory persistence, rollback and historical access across restart.
It requires CREATE SCHEMA permission in addition to ordinary app permissions.

## 12. Runbook for teammates

Run Git commands from the checkout root. Run Python commands below from `backend`
unless stated otherwise. Preserve local configs and ignored secrets.

### A. Confirm the intended code is running

```sh
git status --short --branch
git fetch origin
git log -5 --oneline
git log --oneline main..origin/gameLogic
```

For a clean checkout on main, `git pull --rebase` updates it. If working on another
branch, compare it deliberately; an ordinary pull does not necessarily include
main's navigation fixes. Do not force/reset away teammates' work or calibration.

### B. Install and run a deterministic backend demo

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
unset DATABASE_URL
export SQLITE_PATH=./lovebugs.sqlite3
.venv/bin/python -m app.persistence init
.venv/bin/python -m app.persistence check
GAME_MODE=simulation AUTONOMY_ENABLED=true AUTONOMY_PROVIDER=mock \
  .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Use a single backend worker. Start the game through the dashboard lifecycle control.
For Gemini, supply the key only to the backend and choose `AUTONOMY_PROVIDER=gemini`.
Do not show keys in screenshots, commit them, or send them to the browser.

### C. Frontend

In a second terminal, from the repository root:

```sh
cd frontend
nvm use
npm ci
npm run dev
```

Node 24 is the project runtime (`frontend/.nvmrc`). For a remote backend, set the
local frontend `VITE_API_BASE_URL` and restart Vite. Configure backend
`FRONTEND_ORIGINS` for the actual browser origin. Confirm that the dashboard is
using backend state, not the offline fallback.

### D. Camera-only localization

```sh
.venv/bin/python -m app.vision --camera 1
# Or development footage, with clean EOF:
.venv/bin/python -m app.vision --video /path/to/overhead.mp4
```

Camera index 1 is the teammate's reported working example, not a universal index.
macOS must authorize the terminal to access the camera; Continuity Camera must
be available. The original user's laptop could not use it, so hardware tests were
performed on a teammate's laptop.

### E. Draw the physical arena and buildings

```sh
.venv/bin/python -m app.navigation.calibrate --camera 1 --config traffic_config.json
```

SPACE freezes the settled image. A selects arena drawing; B adds building boxes;
W/E selects each robot's entire body box and then its marker-center click. U undoes
the last building. S saves. Q exits. Include wheels, attachments and overhangs.
Keep speed/latency settings measured; the geometry editor does not measure speed.
Review and set `calibrated: true` only after checking the saved settings.

### F. Inspect routes, then test motion

```sh
.venv/bin/python -m app.navigation --camera 1 --phase 3 \
  --robots-config navigation_robots.json --traffic-config traffic_config.json
```

Expect arena/building boxes, footprint circles, a TRAFFIC line and checked route
segments. Phase 3 never connects to BLE. Select W/E and click targets in open
space. Test a building-interior target and an out-of-arena target: both must be
rejected. Test a path requiring a detour around a building/parked peer.

After successful dry-run and physical calibration checks:

```sh
.venv/bin/python -m app.navigation --camera 1 --phase 4 \
  --robots-config navigation_robots.json --traffic-config traffic_config.json
```

W/E selects a robot, click sets its target, A arms it. Arm both to queue both
trips; one moves at a time. SPACE stops both; Q stops/exits. Start with short clear
routes before building-adjacent ones. Never interpret a STOP reason as permission
to disable the guard. Phase 4 rejects prerecorded video and the old single-robot
CLI path. On current main the traffic flag is optional only because its file has
a default; traffic protection itself is mandatory.

### G. Connect real navigation to the game

Start the backend with `GAME_MODE=hardware` and mock autonomy first. On the
camera/BLE laptop:

```sh
.venv/bin/python -m app.navigation --camera 1 --phase 4 \
  --robots-config navigation_robots.json --traffic-config traffic_config.json \
  --backend-url http://BACKEND_LAN_IP:8000
```

Use `127.0.0.1` if backend and camera run on the same machine. Set backend map
location points to reachable physical service points. Start the game, wait for
fresh telemetry, and press A in the camera window to enable task following.
In this mode click targets are disabled. New authoritative tasks can execute
under that permission; SPACE, stop/reset, health/authority loss or safety faults
revoke it. A is required again after interruptions. Backend data older than
0.75 seconds is not trusted for continuing motion.

Physical arrival reports must match session/task/location. The backend then owns
activity timing, collection rewards and sale effects. Verify UI coins with those
confirmed transitions, not chat text. `blocked` is reported in health telemetry;
traffic messages use the additive `/agent-chat/traffic` endpoint.

### H. Local environment file / Tiger Data

Put credentials locally in ignored `backend/.env`; do not overwrite an existing
file. Explicit loading is required:

```sh
.venv/bin/python -m app.persistence init --env-file .env
.venv/bin/python -m app.persistence check --env-file .env
.venv/bin/python -m uvicorn app.main:app --env-file .env --host 0.0.0.0 --port 8000
```

Existing shell variables take precedence, including an empty DATABASE_URL. Set
GAME_MODE/AUTONOMY values deliberately for this process. Plain `python -m
app.agents` does not automatically load that file. For the live test, export a
TEST_DATABASE_URL locally as described in the backend README; no URL is supplied
in this document.

## 13. Verification record and boundaries of evidence

At implementation commit `2da2936`:

- Backend unittest discovery ran **173 tests**, succeeded, with **one skipped**:
  the credential-dependent live Tiger Data test.
- Real localhost HTTP/WebSocket smoke test passed: lifecycle, movement/arrival,
  collection, sales/purchases, idempotent rewards, history, pose/health, world
  WebSocket, mock chat, CORS and reset/stop/resume.
- The last frontend production build passed after traffic-chat UI integration,
  using Node 24. Subsequent changes before this handoff were backend/docs only.
- Navigation tests include generated ArUco input and mocked BLE/UI, plus pure
  geometry/traffic tests. They do not prove stopping distance, turn sign, camera
  latency or real collision avoidance on the physical arena.
- Neither the watchdog sketch nor live Tiger nor the full physical round has a
  successful verification record in this conversation.

Reproduce from `backend`:

```sh
.venv/bin/python -m unittest discover -s tests -q
PYTHONPATH=. .venv/bin/python tests/http_smoke.py
# With a locally configured, authorized TEST_DATABASE_URL:
.venv/bin/python -m unittest discover -s tests -p test_persistence.py -v
```

The HTTP smoke test uses a temporary SQLite database and a local server. A skipped
hosted test is not evidence that Tiger Data works. After merging gameLogic, rerun
its expanded tests and the existing navigation/persistence tests together; the
173-test count belongs to this main snapshot, not to the merged future code.

## 14. Unmerged teammate work: inspect before implementing more gameplay

At this snapshot `origin/gameLogic` has these commits not yet in main (selected
functional changes, in approximate dependency order):

| Commit | Branch work |
| --- | --- |
| `26f1ca4`, `face510` | Growing-crops panel, crop queue and market notifications. |
| `809e90e` | Authoritative farm plots. |
| `98c8eef` | Authoritative PLANT task. |
| `5aabeb3`, `ffc5881`, `ec9ad11` | Crop readiness, plot-aware harvesting and automated crop queue lifecycle. |
| `cd6d2ab` | Carrot and pumpkin lifecycles. |
| `bc1603c` | Cooperative stage economy. |
| `6eb14fc` | Strategic tiered fishing. |

Branch code/docs claim full three-crop lifecycles, retry-safe transfers and money
requests, proposals/responses and contributions, and fishing with an outcome/time
fixed per attempt. These are branch claims/code inventory, not newly verified
physical behavior or merged main functionality. Compare the updated contracts,
planners, schemas and tests before integrating.

Suggested merge review:

1. Fetch and compare both tips in a separate review branch/worktree if needed.
2. Preserve main's mandatory traffic default, calibration editor and firmware
   archive/variant. Preserve gameLogic's authoritative crop/economy semantics.
3. Reconcile shared `main.py`, configuration, agent chat/planners/runtime,
   persistence tests and READMEs rather than selecting an entire side blindly.
4. Check hardware navigation for new actions: a PLANT task may still navigate to
   a location, but arrival/activity/economy effects must use the new backend rules.
   Ensure traffic narration does not accidentally authorize an economy proposal.
5. Re-run full tests, HTTP smoke and frontend build. Review changed event/data
   shapes together with UI consumers and history serialization.
6. Only then merge through the team's agreed Git workflow and repeat a hardware
   mock rehearsal. Do not force-push shared branches.

## 15. Recommended next steps and alternative avenues

### Recommended: prove a small physical loop before expanding the arena

**Milestone 1 — Guarded movement.** Record exact checkout revision/config path;
review measured radii/speed/latency; verify both corrected headings; test arena,
building and peer rejection in phase 3; then short phase-4 routes. Confirm actual
STOP on SPACE, lost marker, BLE disconnect and firmware command expiry. Exit:
repeatable routes around the real buildings with no bypass or unexplained drift.

**Milestone 2 — One physical task end to end.** Keep mock autonomy or assign one
known task. Check task ID → physical movement → arrival → backend activity → one
inventory change, then market → one sale → gold. Test a cancelled task too. Exit:
the UI and history match observed physical progress with no duplicate reward.

**Milestone 3 — Two robots and conversation.** Queue both with separated service
points; observe deterministic waiting and the narrated right-of-way decision.
Keep one-mover traffic until repeated rehearsals are reliable. Exit: useful work
continues, chat stays understandable, and a stop/reset interrupts both safely.

**Milestone 4 — Database and full rehearsal.** Supply the live Tiger URL locally,
run the isolated integration test, initialize/check the intended service, and
record a complete round. Verify fresh-session/history semantics. Run mock first,
then Gemini using the same controls. Exit: at least several complete repeatable
rounds and a known simulation fallback for the presentation.

### Avenue A: reliable baseline demo

Freeze game expansion, retain main's simple harvesting/fishing loop, tune route
lengths and reward timing to a short understandable round, add a clear victory
presentation. This minimizes simultaneous integration risk and is the shortest
path to proving the physical/backend/UI stack.

### Avenue B: integrate the teammate's richer game

Merge and verify gameLogic in a deliberate integration pass, then demonstrate
planting/progression/cooperative economy. This better matches GAME_DESIGN, but
adds more states, task timing and UI interactions to validate. Do not implement
parallel versions of mechanics that already exist on that branch.

### Avenue C: improve traffic after the baseline works

If the bounded detour controller frequently stops despite sensible calibration,
consider a small fixed waypoint/lane graph and explicit waiting bays/service
slots. This can be easier to rehearse than unrestricted paths in a tight arena.
Add deadlock recovery and eventually independent-lane concurrency only with
clear reservation and stopping rules. Keep emergency control deterministic.
A future bumper sensor would enable actual contact detection; the current camera
and one-character BLE interface do not provide it.

### Avenue D: improve calibration and observability

Next useful additions are a clear calibration review/enable screen instead of
manual JSON approval, displaying desired steering toward the active waypoint,
logging compact stop reasons and config/version identifiers, and eventually
camera/world homography if perspective error is material. The current guard is
conservative; measure the source of stopping/drift before changing margins.

## 16. Suggested division of work

| Owner/workstream | Concrete next deliverable |
| --- | --- |
| Camera/robot teammate | Actual calibrated JSON, verified watchdog flashing, short recorded guarded-route and stop tests. |
| Game/backend teammate | Review/merge gameLogic contracts and effects; prove one task and sale against hardware arrivals. |
| Frontend teammate | Clear backend-vs-fallback indication, task/blocked/traffic visibility, victory presentation and later economy panels. |
| Agent teammate | Verify decisions against merged crop/economy rules and keep useful messages concise; no LLM motor commands. |
| Database teammate | Provide URL locally, run isolated Tiger test, check real service permissions/hypertables and history retrieval. |
| Integration owner | Pin tested commit/config versions and run the full acceptance scenario before adding more features. |

## 17. Instructions to another Codex picking this up

Read `AGENTS.md`, this handoff, and the relevant implementation before editing.
Run status/pull first. Preserve local physical calibration and secret files. Do not
claim any unmerged gameLogic work is on main or any mocked test is a hardware test.
Do not reintroduce unguarded fleet movement, browser-owned agent dispatch, a second
game backend, or database writes outside accepted authoritative transitions.

At completion, run relevant checks, inspect the diff, commit, sync/rebase safely,
push, and report the commit/checks and any unresolved live verification. Update
this handoff's status/branch references when those facts actually change.
