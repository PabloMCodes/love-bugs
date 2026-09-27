# Love Bugs game plan

> **Gameplay direction update:** [GAME_DESIGN.md](GAME_DESIGN.md) is now the
> authoritative reference for the planned three-stage farming tycoon, fishing,
> cooperative unlocks, and money transfers. The simpler Repair Fund below records
> the current technical baseline and earlier milestone plan. Do not implement its
> generic `tool_upgrade` recommendation without first reconciling the roadmap with
> the newer design.

This document is the shared product and implementation direction for the game.
It explains what the demo is trying to prove, how a round should feel, what is
already implemented, and what each subsystem needs next. The API contract remains
authoritative in [api.md](api.md); this document describes gameplay intent and
planned work.

## One-sentence game

Wall-y and Eve are autonomous robot partners who divide work across a shared
world, gather resources, sell them at the market, and save enough gold to repair
their home.

The demo should make cooperation visible. A spectator should understand what the
robots are trying to accomplish, why each robot chose its current task, how their
separate inventories contribute to one goal, and when the team wins.

## First playable goal

The first cohesive scenario is **The Repair Fund**:

1. A new session begins with both robots at `homebase` and the game in `READY`.
2. The game starts and autonomous planning becomes active.
3. Wall-y primarily harvests wheat at the `farm`; Eve primarily catches salmon at
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
- `robot-a` and `robot-b` are stable integration IDs. Wall-y and Eve are display
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
| `robot-b` | Eve | Salmon at the lake | A distinct route makes parallel work and coordination visible. |

Specialties guide the deterministic mock planner and the Gemini prompt; they are
not hard restrictions in the task API. This keeps recovery possible if a robot is
busy, blocked, offline, or already carrying valuable inventory.

## Current implementation status

| Capability | Status | Notes |
| --- | --- | --- |
| Canonical world and live snapshots | Implemented | `GET /world` and WebSocket `/events` publish full authoritative state. |
| Task lifecycle | Implemented | Move, return home, harvest, fish, buy, and sell are validated and tracked. |
| Simulation | Implemented | Movement, arrival, activity timing, inventory rewards, and trading run without hardware. |
| Individual inventory and wallets | Implemented | The market sell view exposes each robot separately. |
| Shared gold goal | Implemented | Combined wallet balance completes the current `earn_gold` goal. |
| Market purchases | Partial | Items can be bought, but seeds and tool upgrades do not affect gameplay yet. |
| Autonomous decisions | Partial | Planners and an orchestrator exist, but the authoritative backend does not host the orchestrator yet. |
| Robot conversation | Partial | The browser starts discussion rounds and dispatches proposals; it is not yet a backend-owned autonomous loop. |
| Goal presentation | Partial | Goal state exists, but the current dashboard does not clearly present progress, start/reset, or victory. |
| Hardware boundary | Ready for integration | Pose, health, blocked, arrival, freshness, and safety contracts exist; real adapters remain teammate work. |
| Persistence/history | Implemented | Accepted transitions and pose history persist through SQLite or Tiger Data. |

## Known gameplay gaps

These are the highest-value gaps to close before adding more content:

1. **The round does not explain itself.** The UI needs a visible objective,
   current/target gold, game status, and a clear completion state.
2. **Autonomy depends on the browser.** Closing the operator tab stops discussion
   rounds. The backend should own the autonomous scheduler; the chat should report
   decisions rather than cause them.
3. **Agent sell validation and the canonical market model disagree.** Buyable items
   live in `market.items`, while sellable items live in robot inventories. The
   authoritative planner must validate `SELL` against inventory, like the task
   service already does.
4. **Purchases are currently cosmetic inventory.** Seeds and the tool upgrade cost
   gold but do not unlock or improve actions. Useless purchases make autonomous
   behavior look incorrect.
5. **The seeded world skips the beginning of the story.** Robots currently start
   at the lake and market with several unrelated resources. A new round should
   start from a deliberate, easily explained setup.
6. **Balancing is still placeholder data.** The target, starting gold, yields,
   prices, travel speed, and activity duration need one measured demo pass.

## Scope for the first complete demo

### Included

- Two autonomous robots: Wall-y and Eve.
- Four locations: homebase, farm, lake, and market.
- Two collection actions: wheat harvesting and salmon fishing.
- Per-robot inventory and wallets.
- A shared gold target and a visible victory state.
- Deterministic mock autonomy for reliable demos.
- Optional Gemini autonomy using the same allowed actions.
- Simulation/hardware switching behind the same contract.
- Stop, reset, offline, stale-tracking, and blocked safety behavior.

### Deferred until the loop is reliable

- Planting and crop-growth cycles.
- Dynamic prices, auctions, or a complex economy.
- Inventory transfers between robots.
- More locations, resources, or robots.
- Combat, enemies, health, or damage.
- A countdown loss condition.
- Camera video inside the dashboard.
- Multiplayer or remote public deployment.

Deferring these features is a scope decision, not a rejection. Each can be added
after the acceptance scenario below works in both simulation and hardware modes.

## Roadmap

### Phase 1 — Make the existing loop coherent

Goal: one understandable, deterministic simulation round.

- [ ] Start both robots at homebase with a small, intentional wallet and empty
  sellable inventory.
- [ ] Choose and test one demo goal target. Start with **200 gold** as a tuning
  candidate, then adjust using measured round duration.
- [ ] Keep only wheat and salmon as collected resources for this phase.
- [ ] Fix autonomous `SELL` validation to read the selected robot's inventory.
- [ ] Add a compact goal HUD with game status, combined gold, target, and progress.
- [ ] Add session-level start, stop, and reset controls without restoring manual
  robot-action buttons.
- [ ] Add a clear victory state and prevent post-completion task dispatch.
- [ ] Add an end-to-end test covering collect → inventory → sell → gold → victory.

Exit criterion: a teammate unfamiliar with the code can start the app, understand
the objective immediately, and watch a complete simulated round without issuing
individual robot tasks.

### Phase 2 — Move autonomy into the backend

Goal: the game continues when no browser is open.

- [ ] Host one `AgentOrchestrator` in the backend lifecycle.
- [ ] Tie planning to `RUNNING`; stop it for `READY`, `STOPPED`, and `COMPLETED`.
- [ ] Add explicit configuration for autonomy enabled/disabled and provider
  (`mock` or `gemini`) without exposing API credentials to the browser.
- [ ] Submit autonomous work through the existing authoritative task service.
- [ ] Publish accepted/waiting decisions to the shared conversation feed.
- [ ] Make the frontend conversation panel a spectator/control surface, not the
  owner of round timing.
- [ ] Ensure only one orchestrator can dispatch for a session.

Exit criterion: start the backend and the game, close every browser, wait, and
reopen the frontend to see valid progress and conversation history.

### Phase 3 — Make the market strategic

Goal: purchases create a visible decision instead of dead inventory.

- [ ] Give `tool_upgrade` one simple effect. Recommended first effect: the owning
  robot collects one additional resource per completed harvest or fishing task.
- [ ] Limit the upgrade to one purchase and display its owner/effect.
- [ ] Teach both planners to compare the upgrade cost with remaining goal progress.
- [ ] Remove seeds from the market until planting exists, or implement a complete
  seed → plant → grow → harvest loop as a later feature.
- [ ] Test that buying lowers current shared gold and that future rewards apply the
  upgrade exactly once.

Exit criterion: spectators can understand why a robot bought or skipped the
upgrade, and both choices remain capable of finishing the round.

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
| Game/backend | Goal rules, task effects, rewards, market, lifecycle | Existing state and task services | Phase 1 seed/balance changes and sell-validation fix |
| Agent orchestration | Mock/Gemini choices, coordination, scheduling | World snapshots and `POST /tasks` semantics | Host orchestrator in backend lifecycle |
| Frontend | Objective, progress, robot state, market, conversation, victory | `GET /world`, `/events`, lifecycle/task routes | Goal HUD and session-level controls |
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
3. Observe different collection assignments for Wall-y and Eve.
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
| Robot roles | Wall-y farms; Eve fishes | Recovery or balancing needs dynamic reassignment |
| Reliable demo provider | Deterministic mock planner | Gemini behavior passes repeated rehearsals |
| Upgrade effect | +1 collected resource per activity | Economy testing shows a clearer alternative |
| Timer/loss state | Deferred | Hardware loop is reliable with time margin |
| Seed mechanics | Deferred; hide seeds | Planting is implemented as a complete loop |

Any change to an endpoint, world field, event meaning, or task lifecycle must be
coordinated through [api.md](api.md), updated in consumers and examples, and tested
in the same change. Gameplay tuning that does not alter contracts belongs here.
