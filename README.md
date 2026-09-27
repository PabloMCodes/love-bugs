# Love Bugs

Love Bugs is a cooperative robotics game in which Wall-y and Eeva make
high-level decisions, move through a shared physical or simulated world, collect
resources, trade at a market, and work toward one crew goal.

The project is designed so the same game rules run in two modes:

- `simulation`: the backend generates movement and arrival updates for a complete
  demo without cameras or robots.
- `hardware`: localization and navigation teammates provide real telemetry and
  arrival reports while the backend keeps ownership of tasks, inventory, gold,
  market transactions, and victory.

## Start here

- [PROJECT_STATUS.md](PROJECT_STATUS.md): consolidated implementation history,
  current scope, subsystem contracts, verification state, risks, and next goals.
- [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md): historical pre-integration main-branch
  evidence, runbooks, and branch comparison.
- [CAMERA_SETUP_GUIDE.md](CAMERA_SETUP_GUIDE.md): camera, calibration, traffic,
  hardware setup, and troubleshooting runbook.
- [GAME_DESIGN.md](GAME_DESIGN.md): staged farming tycoon, fishing risk/reward,
  cooperative unlocks, money transfers, map progression, and design decisions.
- [GAME_PLAN.md](GAME_PLAN.md): product direction, core loop, current gaps,
  milestones, acceptance criteria, and teammate workstreams.
- [INTEGRATION.md](INTEGRATION.md): practical handoff checklist for each subsystem.
- [api.md](api.md): stable HTTP, WebSocket, and world-state contract.
- [backend/README.md](backend/README.md): backend setup and subsystem details.
- [frontend/README.md](frontend/README.md): dashboard setup and frontend structure.

The current baseline already completes a backend-owned autonomous simulation round:
robots collect, travel, sell their own inventory, jointly fund permanent farming stages,
transfer gold when needed, and complete the shared gold goal. The dashboard now includes a purchase-only seed
market, an authoritative Crop Queue backed by three shared farm plots, transaction
notifications, live robot conversation, hardware-input readiness, cooperative
economy status, session controls, and an authoritative victory celebration.

The authoritative three-crop lifecycle now runs end to end without browser input:
planners compare unlocked Wheat, Carrot, and Pumpkin returns, buy only enough seed
for open capacity, claim distinct plots, plant, wait or fish during growth, harvest
the selected plot once, and sell the crop. Fishing now fixes a seeded 5–15 second
duration and one of three reward tiers exactly once per task; planners compare its
expected return with farming and can request exact seed shortfalls. The Crop Queue
displays every crop with live progress from backend timestamps. See `GAME_PLAN.md`
for the remaining physical acceptance, economy UI, and presentation work.

[`backend/game_config.json`](backend/game_config.json) is the validated demo
profile for service-point coordinates, starting economy, crops, unlocks, and
fishing. The deterministic seed-0 mock round currently completes in about 88
simulated seconds, and unanswered cooperative requests expire so the agents can
recover instead of waiting indefinitely.

During physical rehearsal, `python -m app.game.acceptance --preflight-only`
checks backend-visible robot input readiness, and `python -m app.game.acceptance`
watches a clean session for the complete two-robot crop, economy, and victory
contract. Physical motor/watchdog safety still follows the camera runbook.
