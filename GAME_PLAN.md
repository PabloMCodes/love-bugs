# Love Bugs game plan

> **Gameplay direction update:** [GAME_DESIGN.md](GAME_DESIGN.md) is now the
> authoritative reference for the planned three-stage farming tycoon, fishing,
> cooperative unlocks, and money transfers. The simpler Repair Fund below records
> the current technical baseline and earlier milestone plan. The newer design
> replaces the earlier generic `tool_upgrade` concept with three crop-seed stages.

This document is the shared product and implementation direction for the game.
It explains what the demo is trying to prove, how a round should feel, what is
already implemented, and what each subsystem needs next. The API contract remains
authoritative in [api.md](api.md); this document describes gameplay intent and
planned work.

## One-sentence game

Wall-y and Eeva are autonomous robot partners who divide work across a shared
world, gather resources, sell them at the market, and save enough gold to repair
their home.

The demo should make cooperation visible. A spectator should understand what the
robots are trying to accomplish, why each robot chose its current task, how their
separate inventories contribute to one goal, and when the team wins.

## First playable goal

The first cohesive scenario is **The Repair Fund**:

1. A new session begins with both robots at `homebase` and the game in `READY`.
2. The game starts and autonomous planning becomes active.
3. A robot buys and plants Wheat Seeds, waits for a farm plot to become ready, and
   harvests that exact plot; fishing remains useful while crops grow.
4. Each robot owns its inventory and wallet. Items never teleport between robots.
5. A robot carrying sellable resources travels to the `market` and sells them.
6. The sum of both wallets advances the shared repair-fund goal.
7. At 100 and 150 combined gold, the robots cooperatively propose, accept, and
   fund the next farm stage before its seed becomes available.
8. Reaching the configured gold target after Stage 3 changes the game to
   `COMPLETED`, stops new work, and gives the frontend a clear victory moment.

This goal deliberately uses the systems already built: navigation, collection,
individual inventory, trading, agent decisions, simulation, hardware telemetry,
events, persistence, and live UI updates.

## Core gameplay loop

```text
READY
  ↓ start
Choose complementary work
  ↓
Buy seed, plant, or travel to lake
  ↓
Grow and harvest crops / catch tiered fish
  ↓
Carry resources to market
  ↓
Sell from that robot's inventory
  ↓
Shared gold reaches target? ── no ──→ choose the next task
  │
 yes
  ↓
COMPLETED + victory presentation
```

The robots should perform this loop without individual movement or collection
buttons. Human controls are session-level controls: start, pause/stop, reset, and
the choice between deterministic mock autonomy and Gemini autonomy.

## Gameplay rules to keep stable

- The backend is authoritative for game status, tasks, inventory, wallets,
  prices, activity rewards, and victory.
- `robot-a` and `robot-b` are stable integration IDs. Wall-y and Eeva are display
  names and must not be used for routing.
- Every robot has its own wallet and inventory. The shared goal is derived from
  the combined wallet balance.
- Collection rewards are granted only after confirmed arrival and completion of
  the backend timer.
- Buying or selling happens only at the market and is revalidated when executed.
- Agents choose high-level actions; deterministic navigation owns movement and
  motor commands.
- Simulation and hardware use the same world model and task lifecycle. Hardware
  mode replaces generated pose and arrival updates, not the game rules.
- A refresh or reconnect must reconstruct the current round from the backend
  snapshot without replaying browser-local decisions.

## Robot identities and initial roles

| Stable ID | Name | Initial specialty | Reason |
| --- | --- | --- | --- |
| `robot-a` | Wall-y | Wheat at the farm | Higher-yield resource loop makes its contribution easy to read. |
| `robot-b` | Eeva | Salmon at the lake | A distinct route makes parallel work and coordination visible. |

Specialties guide the deterministic mock planner and the Gemini prompt; they are
not hard restrictions in the task API. This keeps recovery possible if a robot is
busy, blocked, offline, or already carrying valuable inventory.

## Current implementation status

| Capability | Status | Notes |
| --- | --- | --- |
| Canonical world and live snapshots | Implemented | `GET /world` and WebSocket `/events` publish full authoritative state. |
| Task lifecycle | Implemented | Move, return home, harvest, tiered fish, buy, sell, and plant are validated and tracked. |
| Simulation | Implemented | Movement, arrival, activity timing, inventory rewards, and trading run without hardware. |
| Individual inventory and wallets | Implemented | The robot tracker exposes each robot's separate wallet and inventory. |
| Shared gold goal | Implemented | Combined wallet balance completes the `earn_gold` goal only after Stage 3 is active. |
| Market purchases | Implemented | The purchase-only market sells all three seeds; later seeds become eligible at 100 and 150 combined gold, then require a paid cooperative unlock. Purchases and sales create transient parchment notifications. |
| Crop lifecycle | Implemented | Wheat, Carrots, and Pumpkins share authoritative buy, plant, growth, plot-aware harvest, and sale rules. |
| Cooperative economy | Implemented | Retry-safe transfers, money requests, proposal responses, two-robot stage contributions, and 30-second unanswered-request recovery are backend-authoritative. |
| Fishing risk/reward | Implemented | Each attempt fixes a seeded 5–15 second duration and a 70/25/5 fish tier exactly once. |
| Autonomous decisions | Implemented | Mock and Gemini autonomy can compare farming with fishing, coordinate tasks, request exact seed shortfalls, and manage stage proposals through one validated command contract. |
| Robot conversation | Implemented | Backend autonomy publishes accepted decisions to a read-only frontend spectator feed. |
| Goal presentation | Partial | The dashboard presents Farm Stage, combined-gold progress, and lifecycle controls; a dedicated victory presentation remains. |
| Hardware boundary | Ready for physical acceptance | Pose, health, blocked, arrival, freshness, and safety contracts plus the camera/BLE backend bridge exist; calibration, watchdog flashing, and the guarded two-robot run remain. |
| Persistence/history | Implemented | Accepted transitions and pose history persist through SQLite or Tiger Data. |

## Known gameplay gaps

These are the highest-value gaps to close before adding more content:

1. **Victory presentation is still incomplete.** Completion is enforced by the
   backend, but the frontend still needs a clear celebration.
2. **Economy presentation is still incomplete.** The world/event stream contains
   proposals, responses, requests, transfers, and contributions, but the dashboard
   does not yet have a dedicated cooperative-economy panel.
3. **Physical pacing still needs measurement.** The committed configuration
   completes a deterministic seed-0 simulation in about 88 seconds, inside the
   60–120 second target; calibrated robot travel may still require profile tuning.

## Scope for the first complete demo

### Included

- Two autonomous robots: Wall-y and Eeva.
- Four locations: homebase, farm, lake, and market.
- Two collection paths: three-stage crop farming and three-tier fishing.
- Per-robot inventory and wallets.
- A shared gold target and a visible victory state.
- Deterministic mock autonomy for reliable demos.
- Optional Gemini autonomy using the same allowed actions.
- Simulation/hardware switching behind the same contract.
- Stop, reset, offline, stale-tracking, and blocked safety behavior.

### Deferred expansion after the reliable baseline

- Dynamic prices, auctions, or a complex economy.
- Inventory transfers between robots.
- More locations, resources, or robots.
- Combat, enemies, health, or damage.
- A countdown loss condition.
- Camera video inside the dashboard.
- Multiplayer or remote public deployment.

The crop lifecycle, cooperative economy, and tiered fishing are reliable in
simulation. Economy/victory presentation, balancing, and hardware rehearsal are
the active remaining milestones; the broader expansion stays deferred.

## Roadmap

### Phase 1 — Make the existing loop coherent

Goal: one understandable, deterministic simulation round.

- [x] Start both robots at homebase with a small, intentional wallet and empty
  sellable inventory.
- [x] Choose and test one demo goal target. Start with **200 gold** as a tuning
  candidate, then adjust using measured round duration.
- [x] Keep crops and tiered fish as the two collected resource families.
- [x] Fix autonomous `SELL` validation to read the selected robot's inventory.
- [x] Add a compact Farm Stage HUD with combined gold, target, and progress.
- [x] Add session-level start, stop, and reset controls without restoring manual
  robot-action buttons.
- [x] Prevent post-completion task dispatch and cancel remaining work at victory.
- [ ] Add a clear dedicated frontend victory celebration.
- [x] Add an end-to-end test covering collect → inventory → sell → gold → victory.

Exit criterion: a teammate unfamiliar with the code can start the app, understand
the objective immediately, and watch a complete simulated round without issuing
individual robot tasks.

### Phase 2 — Move autonomy into the backend

Goal: the game continues when no browser is open.

- [x] Host one `AgentOrchestrator` in the backend lifecycle.
- [x] Tie planning to `RUNNING`; stop it for `READY`, `STOPPED`, and `COMPLETED`.
- [x] Add explicit configuration for autonomy enabled/disabled and provider
  (`mock` or `gemini`) without exposing API credentials to the browser.
- [x] Submit autonomous work through the existing authoritative task service.
- [x] Publish accepted/waiting decisions to the shared conversation feed.
- [x] Make the frontend conversation panel a spectator/control surface, not the
  owner of round timing.
- [x] Ensure only one orchestrator can dispatch for a session.

Exit criterion: start the backend and the game, close every browser, wait, and
reopen the frontend to see valid progress and conversation history.

### Phase 3 — Make the market strategic

Goal: purchases create a visible decision instead of dead inventory.

- [x] Replace placeholder purchases with wheat, carrot, and pumpkin seeds.
- [x] Enforce stage-based seed availability in the backend.
- [x] Add the purchase-only market, transaction notifications, and Crop Queue UI shell.
- [x] Add the wheat crop definition and three authoritative shared farm plots.
- [x] Add a validated `PLANT` task that consumes one owned seed exactly once.
- [x] Advance crops from `GROWING` to `READY` from backend timestamps and events.
- [x] Make `HARVEST` require a ready plot, grant its crop once, and empty that plot.
- [x] Render ready crops first and show live timestamp-derived growth progress.
- [x] Teach planners to buy Wheat Seeds, reserve distinct plots, plant, and harvest.
- [x] Add Carrot and Pumpkin definitions and compare their value and growth time.
- [x] Test that purchases, planting, growth, harvesting, and sales resolve exactly once.

Exit criterion: spectators can understand why a robot chose a seed, and every
purchase contributes to a complete farming loop instead of dead inventory.

### Phase 4 — Cooperative progression

- [x] Make threshold gold an eligibility check rather than an automatic unlock.
- [x] Require both robots to accept explicit positive contributions.
- [x] Deduct contributions and advance the stage atomically and exactly once.
- [x] Add direct transfers and accept/reject money requests without changing total gold.
- [x] Expire unanswered money requests and unlock proposals so autonomy can replan.
- [x] Teach mock and Gemini autonomy the cooperative economy actions.
- [x] Require Stage 3 as well as the final gold target for victory.
- [ ] Render pending proposals, requests, and completed contributions in the dashboard.

### Fishing strategy

- [x] Resolve a random 5–15 second duration once when a fishing task is assigned.
- [x] Add common, uncommon, and extremely rare fish at 70%, 25%, and 5%.
- [x] Persist the resolved task parameters so retries cannot reroll or pay twice.
- [x] Seed simulation outcomes for repeatable demos and tests.
- [x] Make mock autonomy compare expected fishing return with crop profit rate.
- [x] Request the exact wallet shortfall when a better seed purchase needs help.

### Phase 5 — Hardware rehearsal

Goal: replace simulated motion without changing gameplay behavior.

- [ ] Calibrate camera coordinates and set safe named service points in a copied
  `backend/game_config.json` selected through `GAME_CONFIG_PATH`.
- [ ] Stream fresh pose and health reports for both robots.
- [ ] Connect assigned destinations to deterministic navigation and ESP32 motor
  commands with an onboard command-expiry watchdog.
- [ ] Confirm arrivals through the existing arrival endpoint.
- [ ] Verify stop, reset, blocked, offline, and stale tracking halt motion.
- [ ] Run the complete repair-fund scenario first with mock autonomy, then Gemini.

Exit criterion: switching `GAME_MODE` changes the movement source but not the UI,
task rules, inventory, market, goal, or victory behavior.

### Phase 6 — Balance and presentation

Goal: make the proven loop feel polished and demo-ready.

- [x] Measure the committed deterministic profile at the production simulation
  speed and enforce a 60–120 second round (currently approximately 88 seconds).
- [ ] Recheck pacing with calibrated physical travel and tune a copied profile
  only if the guarded round falls outside the target window.
- [ ] Make task reasons and robot dialogue concise and nonrepetitive.
- [ ] Add sound, celebration, and clearer transition feedback only after state
  correctness is stable.
- [ ] Add a timer or failure condition only if repeated hardware runs leave enough
  reliability margin.

## Teammate workstreams

| Workstream | Owns | Builds against | Immediate handoff |
| --- | --- | --- | --- |
| Game/backend | Goal rules, task effects, rewards, market, lifecycle | Existing state, task, and economy services | Tune cooperative costs and final goal through measured runs |
| Agent orchestration | Mock/Gemini choices, coordination, scheduling | World snapshots plus task/economy command semantics | Tune crop selection through measured demo runs |
| Frontend | Objective, progress, robot state, market, Crop Queue, conversation, victory | `GET /world`, `/events`, lifecycle/task routes | Add later crop art and a clearer victory presentation |
| Localization | Camera-to-world pose and zone calibration | Pose ingestion contract | Continuous fresh pose reports in hardware mode |
| Navigation/control | Destination following, arrival, cancellation, blocked handling | Active task plus map locations | Safe adapter from tasks to robot commands |
| ESP32/robot | Motor execution, health reporting, local watchdog | Private navigation transport | Stop on stale commands and publish health |
| Persistence | Reliable history and session diagnostics | Backend-owned transitions | Keep gameplay writes atomic and queryable |

Subsystems coordinate through stable IDs and documented APIs. A teammate should
not need another subsystem's internal module to make progress.

## End-to-end acceptance scenario

The first complete milestone must pass this script:

1. Reset into a new simulation session and confirm both robots are at homebase.
2. Start the game with deterministic mock autonomy.
3. Observe different collection assignments for Wall-y and Eeva.
4. Observe simulated movement, confirmed arrival, active progress, and one reward
   per completed activity.
5. Confirm each reward enters only the acting robot's inventory.
6. Observe at least one robot travel to the market and sell its own inventory.
7. Confirm inventory decreases, that robot's wallet increases, and shared goal
   progress equals the sum of both wallets.
8. Watch both robots approve and fund Stage 2 and Stage 3 without duplicate deductions.
9. Reach the target after Stage 3, transition exactly once to `COMPLETED`, stop new dispatch,
   and show victory in the frontend.
10. Refresh the browser and confirm the completed state is reconstructed.
11. Repeat with a mid-route stop/reset and confirm no cancelled task grants a reward.

The same scenario is the hardware acceptance test, except pose and arrival updates
come from the real adapters instead of `SimulationRunner`.

## Team decisions and defaults

| Decision | Working default | Revisit when |
| --- | --- | --- |
| Primary objective | Combined wallet reaches repair-fund target | A different goal is implemented end to end |
| Demo target | 200 gold, approximately 88-second deterministic simulation | Calibrated physical round is outside 60–120 seconds |
| Robot roles | Wall-y farms; Eeva fishes | Recovery or balancing needs dynamic reassignment |
| Reliable demo provider | Deterministic mock planner | Gemini behavior passes repeated rehearsals |
| Timer/loss state | Deferred | Hardware loop is reliable with time margin |
| Seed catalog | Wheat 5; carrot 10; pumpkin 20 | Simulation balancing produces better values |
| Seed mechanics | All three crops share the authoritative lifecycle | Balance testing exposes a rule problem |
| Farm model | Start with three shared plots; queue is derived from nonempty plots | Simulation makes a different capacity clearer |
| Crop balance | Wheat 8s/36 gross; Carrot 12s/60; Pumpkin 18s/96 | Physical demo pacing favors different values |

Any change to an endpoint, world field, event meaning, or task lifecycle must be
coordinated through [api.md](api.md), updated in consumers and examples, and tested
in the same change. Gameplay tuning that does not alter contracts belongs here.
