# Love Bugs tycoon game design

Status: **core game logic implemented; presentation, balancing, and hardware rehearsal remain**.

This document records the intended mechanics and the boundary between implemented
gameplay and planned expansion. It is the product reference for farming progression,
fishing, money, cooperation, and map changes. Current values are working defaults
that remain subject to measured balance passes.

The existing API and implementation are described in [api.md](api.md). Planned
mechanics in this document do not change that stable contract until the related
schema, endpoints, tests, examples, and consumers are updated together.

## Current implementation checkpoint

The backend supports a reliable autonomous resource loop, the complete three-crop
lifecycle, cooperative stage progression, money requests/transfers, and
multi-tier fishing. The market sells all three seed types and enforces stage
locks. The frontend has a purchase-only market, market transaction notifications,
and a full-height Crop Queue driven by canonical farm state.

Schema version 4 includes Wheat, Carrot, and Pumpkin definitions and three shared
farm plots. `PLANT` consumes one owned seed at the farm and atomically creates a
timestamped `GROWING` plot, which the queue renders. The backend game loop changes
elapsed plots to `READY` exactly once and publishes `crop_ready`. `HARVEST` requires
a selected ready plot, grants its configured crop once, publishes `crop_harvested`, and
returns the plot to `EMPTY`. Mock autonomy maintains the queue by buying only for
unreserved empty capacity, planting owned seeds into distinct plots, harvesting
ready crops, and selling the result. Fishing resolves a seeded 5–15 second timer
and one of three reward tiers exactly once at assignment. Mock autonomy compares
expected fishing income with crop profit rate and can request an exact seed-funding
shortfall. Gemini receives the same validated state and decision contract.

## Game fantasy

Wall-y and Eeva run an autonomous farming and fishing business. They decide how to
spend their own money, which activities are worth their time, when to take a safe
farming return, and when to gamble on fishing. Their long-term objective is to
grow the business through three crop stages and reach the final money goal.

The game should feel like a small cooperative tycoon:

- Farming is predictable, progressive, and increasingly profitable.
- Fishing is always available, unpredictable, and never upgraded.
- Each robot owns its own inventory and wallet.
- Major progression requires communication and agreement between both robots.
- The map visibly evolves as the business reaches new stages.

## Round structure

```text
Stage 1: Wheat
  ↓ reach the carrot threshold
Cooperative carrot unlock
  ↓
Stage 2: Carrots
  ↓ reach the pumpkin threshold
Cooperative pumpkin unlock
  ↓
Stage 3: Pumpkins
  ↓ reach the final money target
Tycoon goal completed
```

At every stage, an idle robot may choose between the deterministic crop economy
and the variable fishing economy. The robots can divide roles, switch strategies,
or help one another finance the next unlock.

## Farming system

### Market rule

The only items robots can purchase from the market are seeds. Generic tool
upgrades and other buyable inventory are removed from this design.

The seed catalog contains exactly three progression items:

| Stage | Seed | Speed | Seed cost | Crop value | Availability |
| --- | --- | --- | --- | --- | --- |
| 1 | Wheat seeds | 8 seconds | 5 gold | 3 × 12 gold | Unlocked when the round begins |
| 2 | Carrot seeds | 12 seconds | 10 gold | 3 × 20 gold | Unlocked at 100 combined gold for now |
| 3 | Pumpkin seeds | 18 seconds | 20 gold | 3 × 32 gold | Unlocked at 150 combined gold for now |

The qualitative relationship is a firm design rule:

```text
wheat grow time < carrot grow time < pumpkin grow time
wheat seed cost < carrot seed cost < pumpkin seed cost
wheat sale value < carrot sale value < pumpkin sale value
```

These are explicit simulation candidates, not final balance. They ensure every crop
has a positive return, longer crops produce a larger sale, and the planner can
compare net profit per growth second. Earlier crops remain available for faster
turnaround even after later stages unlock.

### Crop lifecycle

The intended farming lifecycle is:

```text
Buy unlocked seed at market
  ↓
Seed enters that robot's inventory
  ↓
Travel to farm
  ↓
Plant one seed
  ↓
Seed is consumed and crop begins its timer
  ↓
Crop becomes ready after its configured grow time
  ↓
Harvest ready crop into the acting robot's inventory
  ↓
Travel to market and sell crop
```

Planting, growing, and harvesting must be backend-authoritative. A crop continues
growing after the robot leaves the farm. Rewards are created only when a ready
crop is harvested; a cancelled planting or harvesting task must not duplicate a
seed or crop.

### Farm capacity

The farm needs explicit plot ownership or capacity so planting is not an
unbounded timer generator. The initial implementation should use the smallest
model that still creates decisions. Recommended starting point:

- A small shared set of farm plots.
- One crop per plot.
- A plot records crop type, planter, planted time, ready time, and state.
- Either robot may harvest a ready shared plot unless playtesting shows that crop
  ownership is more understandable.

The working implementation default is **three shared plots**. Either robot may
harvest a ready plot. This remains a balancing choice and can change after the
first complete wheat simulation pass.

### Crop Queue implementation goal

The Crop Queue is a view of authoritative plots, not a second queue stored in the
browser. The backend world exposes each plot's stable ID, state (`EMPTY`, `GROWING`,
or `READY`), crop type, planter, planted timestamp, and ready timestamp. The
frontend omits empty plots from the active queue, shows ready crops first, then
sorts growing crops by `ready_at`. Growing cards derive a live countdown and
progress bar from `planted_at` and `ready_at`; they never advance backend state.
A successful `PLANT` task creates those growing entries from backend state.

The lifecycle was proven with Wheat, then generalized to every crop definition:

1. Buy one unlocked seed through the existing market transaction.
2. Submit `PLANT` at the farm with a seed item and empty plot ID.
3. Atomically consume one seed and create one `GROWING` plot.
4. Transition it once to `READY` from backend-owned time and publish an event.
5. Submit plot-aware `HARVEST`, grant the configured crop once, and return the
   plot to `EMPTY`.
6. Sell the harvested crop through the existing market transaction.

This sequence now passes cancellation, retry, reset, reconnect, live HTTP smoke,
and data-driven Carrot/Pumpkin lifecycle tests.

## Stage progression

Each crop stage has a money threshold. Reaching a threshold makes the next seed
eligible to unlock; it does not silently purchase it.

The backend now uses explicit cooperative unlocks. At 100 combined gold Stage 2
becomes eligible and costs 30 gold; at 150 combined gold Stage 3 becomes eligible
and costs 60 gold. These are current demo tuning values, not final balance.

The cooperative unlock flow is:

1. The robots' combined available money reaches the stage threshold.
2. The next seed unlock becomes available as a shared proposal.
3. Both robots agree to the unlock through their agent decisions/dialogue.
4. The unlock cost is funded from their individual wallets in one atomic
   transaction.
5. The next seed becomes permanently available for the current game session.
6. A progression event is published and the map changes to show the new crop.

This produces a real cooperation moment. One robot cannot silently spend the
other robot's money, and a failed or partial transaction cannot remove funds.

### Contribution rules

The game must support unequal contributions because the robots may have different
balances. A cooperative purchase therefore needs:

- The total unlock cost.
- Each robot's proposed contribution.
- Consent from both robots.
- Validation that each contribution is affordable when the purchase executes.
- One atomic deduction and one unlock event.
- Cancellation or timeout behavior if agreement is not completed.

Both robots currently must contribute a positive whole amount. Unequal splits are
valid, but the proposed contributions must total the configured cost and remain
affordable when the final acceptance executes.

## Individual economy

Wall-y and Eeva always retain separate:

- Wallet balances.
- Seed inventories.
- Harvested crop inventories.
- Fish inventories.
- Active tasks.

Buying seeds removes money only from the buyer. Selling crops or fish adds money
only to the seller. Shared stage eligibility may inspect their combined money,
but the wallets are not automatically merged.

This distinction should be visible in the robot tracker and market. It is also
important for agent reasoning: the team may be wealthy enough in total while the
robot currently at the market cannot afford its intended purchase.

## Money requests and transfers

A robot that cannot afford a seed or proposed stage contribution may ask its
teammate for money.

The implemented transfer flow is:

1. Requesting robot states the amount and purpose.
2. Teammate accepts or rejects the exact request.
3. An accepted transfer is revalidated against the sender's current wallet.
4. The backend moves the money atomically between wallets.
5. Both the dialogue feed and semantic event feed show the result.

Transfers do not create or destroy gold and do not directly advance a combined
money goal. Requests need stable IDs so retries cannot transfer money twice.

The robots should use transfers for a concrete plan, not continuously rebalance
their wallets without reason.

## Fishing system

Fishing is the permanent risk/reward alternative to farming. It is available at
the lake during all three stages and has no unlocks or upgrades.

### Fishing action

- The robot travels to the lake.
- A fishing attempt takes a random **5–15 seconds**.
- Completion catches exactly one fish.
- The fish tier is selected randomly.
- The fish enters the acting robot's inventory.
- The robot must sell it at the market to receive money.

### Fish tiers

| Tier | Sale value | Frequency |
| --- | ---: | --- |
| Common fish | $1 | 70% |
| Uncommon fish | $5 | 25% |
| Extremely rare fish | $15 | 5% |

The working distribution has an expected value of 2.7 gold per attempt, or 0.27
gold per second at the mean 10-second duration. Tests and simulation use an
injectable/seeded random source; hardware play uses runtime randomness unless a
seed is explicitly configured. Duration and tier are resolved and stored when the
task is assigned, so travel, reconnects, retries, and cancellation cannot reroll
or duplicate the result.

Fishing never becomes faster and its reward table never improves when farming
stages unlock. Its strategic role changes naturally: it may be attractive early,
useful while crops grow, or a risky attempt to close a small funding gap.

## Agent decision space

Agents continue to select bounded high-level actions. The expanded game should
let them reason about:

- Which seeds are currently unlocked.
- Seed price, grow time, crop sale value, and free farm plots.
- Crops currently growing or ready to harvest.
- Their own wallet and inventory.
- Their teammate's wallet, inventory, location, and active task.
- Current stage threshold and final money target.
- Expected fishing time/value and its uncertainty.
- Whether to save, buy, plant, harvest, sell, fish, request money, transfer money,
  contribute to an unlock, or wait.

Candidate high-level actions are:

- `BUY_SEED`
- `PLANT`
- `HARVEST`
- `FISH`
- `SELL`
- `REQUEST_MONEY`
- `TRANSFER_MONEY`
- `PROPOSE_UNLOCK`
- `ACCEPT_UNLOCK`
- `MOVE_TO`
- `RETURN_HOME`
- `WAIT`

These are design concepts, not frozen API names. Before implementation, the team
should decide which actions become public tasks, which are game-service commands,
and which remain internal agent decisions.

Agent dialogue should communicate actionable coordination, for example:

- Who will farm and who will fish.
- Which plot or crop needs attention.
- Why a robot is saving instead of buying.
- A money request and its purpose.
- Proposed contributions to the next unlock.
- Agreement or rejection of an unlock.

Dialogue must describe authoritative actions; it must not claim that a transfer,
purchase, planting, or unlock succeeded before backend confirmation.

## Map progression

The world map must visibly reflect the current farming stage:

- Stage 1 shows wheat at the farm.
- Stage 2 introduces carrots at the farm.
- Stage 3 introduces pumpkins at the farm.

The backend should expose stage and farm state; the frontend should render them.
The frontend must not infer a stage from wallet balances because an unlock also
requires agreement and payment.

Minimum implementation: change the farm artwork or overlay when the highest
unlocked crop changes. Preferred later implementation: render planted, growing,
and ready plots from authoritative farm data.

Whether earlier crops remain visually present and purchasable after later stages
unlock is still open. The initial recommendation is cumulative unlocks so agents
retain meaningful fast-versus-profitable choices.

## Victory condition

The game has three progression stages. After pumpkins are unlocked, the team
works toward a final combined-money target. Reaching that target completes the
tycoon goal, stops new autonomous tasks, and triggers the victory presentation.

The following values must be balanced later:

- Carrot eligibility threshold and unlock cost.
- Pumpkin eligibility threshold and unlock cost.
- Final money target.
- Starting money per robot.
- Seed costs and crop sale values.
- Grow times and farm plot count.
- Fishing-tier probabilities after measured playtesting.

Unlock costs and the final target should be achievable through multiple viable
strategies rather than one scripted sequence.

## Authoritative state the design will need

These fields now live in the canonical version-4 world schema:

- Current stage and unlocked seed IDs.
- Stage thresholds, costs, and final target.
- Seed definitions with cost and growth duration.
- Crop definitions with sale value.
- Farm plots with crop type, state, planter, and timing.
- Pending cooperative unlock proposal and contributions.
- Pending money request or transfer proposal.
- Fishing attempt timing and resolved fish tier.
- Events for planting, crop readiness, harvesting, transfers, unlocks, and stage
  changes.

Random outcomes, timers, contributions, and rewards must be persisted or otherwise
resolved exactly once so reconnects and retries cannot reroll or duplicate them.

## Balancing principles

- Farming provides predictable positive returns.
- Longer crops pay more in absolute profit.
- Earlier crops remain useful when speed or a small funding gap matters.
- Fishing has higher variance but a controlled expected return.
- Waiting for crop growth creates a reason for the second robot to do different
  work instead of duplicating the same task.
- Cooperative unlock costs are large enough to require planning but not so large
  that one unlucky fishing streak stalls the game.
- A full simulated round should eventually be tuned to a reliable demo length.

## Acceptance scenarios

### Farming progression

1. Wall-y buys wheat seed and only Wall-y's wallet decreases.
2. Wall-y plants it in a free plot; the seed is consumed once.
3. The plot becomes ready only after the wheat timer completes.
4. Harvest adds wheat to one robot's inventory exactly once.
5. Selling at the market removes the wheat and credits only the seller.

### Fishing

1. Eeva starts fishing at the lake.
2. One duration from 5–15 seconds is fixed for that attempt.
3. Completion resolves one fish tier exactly once.
4. The fish remains in Eeva's inventory until sold.
5. Seeded tests can reproduce duration and tier outcomes.

### Cooperative unlock

1. Combined money reaches the carrot eligibility threshold.
2. One robot proposes the unlock and contributions.
3. No funds move before the other robot accepts.
4. Acceptance atomically deducts valid contributions and unlocks carrot seeds.
5. Retries cannot deduct twice or publish duplicate unlocks.
6. The farm map changes to the carrot stage for every connected client.

### Money transfer

1. A robot requests money for a named purchase or contribution.
2. Rejection changes no balances.
3. Acceptance debits the sender and credits the receiver atomically.
4. Insufficient funds at execution fails without a partial transfer.

### Final stage

1. The team unlocks wheat, carrots, and pumpkins in order.
2. Earlier seeds follow the chosen cumulative-availability rule.
3. Combined money reaches the final target after pumpkin stage is active.
4. The game completes exactly once and autonomous dispatch stops.

## Open decisions before later phases

- Final tuning of seed costs, grow times, and crop sale values.
- Stage eligibility thresholds, cooperative unlock costs, and final target.
- Final farm plot count and whether playtesting justifies planter-only harvesting.
- Proposal timeout and cancellation behavior.
- Whether earlier seeds remain available after later stages unlock.
- Final fishing-tier probabilities after measured playtesting.
- Proposal and money-request history retention beyond the current game session.
- Whether harvested crops need a short completed-history section in the queue.

## Suggested implementation order

No implementation begins merely because it appears in this document. When the
team is ready, the safest order is:

1. Add map stage rendering and crop-specific farm presentation.
2. Render cooperative proposals, requests, and transfers in the dashboard.
3. Tune the implemented fishing distribution against full-round simulation data.
4. Tune the complete autonomous loop in simulation before connecting physical motion.
