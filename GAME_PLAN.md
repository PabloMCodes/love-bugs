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
3. Wall-y primarily harvests wheat at the `farm`; Eeva primarily catches salmon at
   the `lake`. Either robot may take another valid task when coordination requires it.
4. Each robot owns its inventory and wallet. Items never teleport between robots.
5. A robot carrying sellable resources travels to the `market` and sells them.
6. The sum of both wallets advances the shared repair-fund goal.
7. Reaching the configured gold target changes the game to `COMPLETED`, stops new
   work, and gives the frontend a clear victory moment.

This goal deliberately uses the systems already built: navigation, collection,
individual inventory, trading, agent decisions, simulation, hardware telemetry,
events, persistence, and live UI updates.

## Core gameplay loop

```text
READY
  ↓ start
Choose complementary work
  ↓
Travel to farm / lake
  ↓
Harvest wheat / catch salmon
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
| Task lifecycle | Implemented | Move, return home, harvest, fish, buy, and sell are validated and tracked. |
| Simulation | Implemented | Movement, arrival, activity timing, inventory rewards, and trading run without hardware. |
| Individual inventory and wallets | Implemented | The robot tracker exposes each robot's separate wallet and inventory. |
| Shared gold goal | Implemented | Combined wallet balance completes the current `earn_gold` goal. |
| Market purchases | Partial | The purchase-only market sells wheat, carrot, and pumpkin seeds; later seeds unlock permanently at 100 and 150 combined gold. Purchases and sales create transient parchment notifications. |
| Crop Queue | UI scaffold | A full-height queue panel is present, but it remains at `0 active` because the world has no authoritative farm plots yet. |
| Autonomous decisions | Implemented | The backend can host one mock or Gemini orchestrator for the authoritative session. |
| Robot conversation | Implemented | Backend autonomy publishes accepted decisions to a read-only frontend spectator feed. |
| Goal presentation | Partial | The dashboard presents Farm Stage, combined-gold progress, and lifecycle controls; a dedicated victory presentation remains. |
| Hardware boundary | Ready for integration | Pose, health, blocked, arrival, freshness, and safety contracts exist; real adapters remain teammate work. |
| Persistence/history | Implemented | Accepted transitions and pose history persist through SQLite or Tiger Data. |

## Known gameplay gaps

These are the highest-value gaps to close before adding more content:

1. **The farm is not authoritative yet.** There are no farm plots, `PLANT` task,
   growth timestamps, ready crops, or plot-aware harvest validation.
2. **The Crop Queue is display-only.** It must render nonempty backend plots sorted
   by readiness instead of maintaining browser-local timers or crop state.
3. **Planners still use the legacy loop.** Mock and Gemini autonomy harvest free
   wheat or fish, then sell; neither buys, plants, waits for, or harvests a plot.
4. **Victory presentation is still incomplete.** Completion is enforced by the
   backend, but the frontend still needs a clear celebration.
5. **Balancing is still placeholder data.** The target, starting gold, yields,
   prices, travel speed, and activity duration need one measured demo pass.

## Scope for the first complete demo

### Included

- Two autonomous robots: Wall-y and Eeva.
- Four locations: homebase, farm, lake, and market.
- Two collection actions: wheat harvesting and salmon fishing.
- Per-robot inventory and wallets.
- A shared gold target and a visible victory state.
- Deterministic mock autonomy for reliable demos.
- Optional Gemini autonomy using the same allowed actions.
- Simulation/hardware switching behind the same contract.
- Stop, reset, offline, stale-tracking, and blocked safety behavior.

### Next expansion after the reliable baseline

- Authoritative planting, crop-growth, and plot-aware harvesting.
- Dynamic prices, auctions, or a complex economy.
- Inventory transfers between robots.
- More locations, resources, or robots.
- Combat, enemies, health, or damage.
- A countdown loss condition.
- Camera video inside the dashboard.
- Multiplayer or remote public deployment.

The crop lifecycle is the active next milestone. The remaining features stay
deferred until that lifecycle is reliable in simulation and the existing hardware
safety boundary remains intact.

## Roadmap

### Phase 1 — Make the existing loop coherent

Goal: one understandable, deterministic simulation round.

- [x] Start both robots at homebase with a small, intentional wallet and empty
  sellable inventory.
- [x] Choose and test one demo goal target. Start with **200 gold** as a tuning
  candidate, then adjust using measured round duration.
- [x] Keep only wheat and salmon as collected resources for this phase.
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
- [ ] Add authoritative crop definitions and a small shared set of farm plots.
- [ ] Add a validated `PLANT` task that consumes one owned seed exactly once.
- [ ] Advance crops from `GROWING` to `READY` from backend timestamps and events.
- [ ] Make `HARVEST` require a ready plot, grant its crop once, and empty that plot.
- [ ] Render ready crops first and growing crops by `ready_at` in the Crop Queue.
- [ ] Teach both planners to compare seed cost, growth time, and expected crop value.
- [ ] Test that purchases, planting, growth, harvesting, and sales resolve exactly once.

Exit criterion: spectators can understand why a robot chose a seed, and every
purchase contributes to a complete farming loop instead of dead inventory.

### Phase 4 — Hardware rehearsal

Goal: replace simulated motion without changing gameplay behavior.

- [ ] Calibrate camera coordinates and named zones against the physical arena.
- [ ] Stream fresh pose and health reports for both robots.
- [ ] Connect assigned destinations to deterministic navigation and ESP32 motor
  commands with an onboard command-expiry watchdog.
- [ ] Confirm arrivals through the existing arrival endpoint.
- [ ] Verify stop, reset, blocked, offline, and stale tracking halt motion.
- [ ] Run the complete repair-fund scenario first with mock autonomy, then Gemini.

Exit criterion: switching `GAME_MODE` changes the movement source but not the UI,
task rules, inventory, market, goal, or victory behavior.

### Phase 5 — Balance and presentation

Goal: make the proven loop feel polished and demo-ready.

- [ ] Tune target, starting gold, rewards, activity durations, and simulation speed
  to produce a reliable 60–120 second round.
- [ ] Make task reasons and robot dialogue concise and nonrepetitive.
- [ ] Add sound, celebration, and clearer transition feedback only after state
  correctness is stable.
- [ ] Add a timer or failure condition only if repeated hardware runs leave enough
  reliability margin.

## Teammate workstreams

| Workstream | Owns | Builds against | Immediate handoff |
| --- | --- | --- | --- |
| Game/backend | Goal rules, task effects, rewards, market, lifecycle | Existing state and task services | Authoritative farm plots plus the wheat plant/grow/harvest slice |
| Agent orchestration | Mock/Gemini choices, coordination, scheduling | World snapshots and `POST /tasks` semantics | Add plot-aware decisions after the wheat slice is validated |
| Frontend | Objective, progress, robot state, market, Crop Queue, conversation, victory | `GET /world`, `/events`, lifecycle/task routes | Render authoritative plots and growth timing in the existing queue shell |
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
8. Reach the target, transition exactly once to `COMPLETED`, stop new dispatch,
   and show victory in the frontend.
9. Refresh the browser and confirm the completed state is reconstructed.
10. Repeat with a mid-route stop/reset and confirm no cancelled task grants a reward.

The same scenario is the hardware acceptance test, except pose and arrival updates
come from the real adapters instead of `SimulationRunner`.

## Team decisions and defaults

| Decision | Working default | Revisit when |
| --- | --- | --- |
| Primary objective | Combined wallet reaches repair-fund target | A different goal is implemented end to end |
| Demo target | 200 gold candidate | Measured round is outside 60–120 seconds |
| Robot roles | Wall-y farms; Eeva fishes | Recovery or balancing needs dynamic reassignment |
| Reliable demo provider | Deterministic mock planner | Gemini behavior passes repeated rehearsals |
| Timer/loss state | Deferred | Hardware loop is reliable with time margin |
| Seed catalog | Wheat 5; carrot 10; pumpkin 20 | Simulation balancing produces better values |
| Seed mechanics | Purchases visible; planting pending | Planting is implemented as a complete loop |
| Farm model | Start with three shared plots; queue is derived from nonempty plots | Simulation makes a different capacity clearer |
| First crop slice | Wheat before generalizing carrot and pumpkin | Wheat passes buy → plant → grow → harvest → sell tests |

Any change to an endpoint, world field, event meaning, or task lifecycle must be
coordinated through [api.md](api.md), updated in consumers and examples, and tested
in the same change. Gameplay tuning that does not alter contracts belongs here.
