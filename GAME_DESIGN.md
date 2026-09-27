# Love Bugs tycoon game design

Status: **captured design direction; not implemented or numerically finalized yet**.

This document records the intended game mechanics before implementation begins.
It is the product reference for farming progression, fishing, money, cooperation,
and map changes. Exact prices, timers, probabilities, and unlock thresholds remain
balancing decisions until they are measured in simulation.

The existing API and implementation are described in [api.md](api.md). Planned
mechanics in this document do not change that stable contract until the related
schema, endpoints, tests, examples, and consumers are updated together.

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
| 1 | Wheat seeds | Quick | 5 gold candidate | Low | Unlocked when the round begins |
| 2 | Carrot seeds | Medium | 10 gold candidate | Medium | Unlocked through the first cooperative progression purchase |
| 3 | Pumpkin seeds | Slow | 20 gold candidate | High | Unlocked through the second cooperative progression purchase |

The qualitative relationship is a firm design rule:

```text
wheat grow time < carrot grow time < pumpkin grow time
wheat seed cost < carrot seed cost < pumpkin seed cost
wheat sale value < carrot sale value < pumpkin sale value
```

These seed prices are initial simulation candidates, not final balance. Crop sale
values and growth times are still open. Final numbers should ensure that every crop
has a positive return and a longer crop produces a meaningfully larger sale,
without making earlier crops immediately useless.

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

The exact number of plots and whether only the planter may harvest are still open
decisions.

## Stage progression

Each crop stage has a money threshold. Reaching a threshold makes the next seed
eligible to unlock; it does not silently purchase it.

The current Repair Fund implementation uses automatic milestone unlocks as an
intermediate step: 100 combined gold permanently unlocks carrot seeds and 150
permanently unlocks pumpkin seeds. The cooperative proposal and contribution flow
below remains the intended replacement once agent transaction actions are added.

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

Whether both robots must contribute a positive amount, or whether one may fund
the entire unlock after both consent, remains an open balancing decision.

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

The intended transfer flow is:

1. Requesting robot states the amount and purpose.
2. Teammate accepts, rejects, or proposes a different amount.
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
| Common fish | $1 | Most likely |
| Uncommon fish | $5 | Less likely |
| Extremely rare fish | $15 | Rare |

The exact probabilities are not decided. They should make fishing feel exciting
without making it the obvious best strategy. Tests and reliable demos need an
injectable or seeded random-number source; production play may use true runtime
randomness.

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
- Fishing-tier probabilities.

Unlock costs and the final target should be achievable through multiple viable
strategies rather than one scripted sequence.

## Authoritative state the design will need

This is a conceptual checklist, not a committed schema:

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

## Open decisions before implementation

- Exact seed costs, grow times, and crop sale values.
- Stage eligibility thresholds, cooperative unlock costs, and final target.
- Farm plot count and crop ownership rules.
- Whether both robots must contribute a positive amount to an unlock.
- Proposal timeout and cancellation behavior.
- Whether earlier seeds remain available after later stages unlock.
- Fish-tier probabilities.
- Whether one robot can have multiple pending money requests.
- Which cooperation actions are tasks versus separate transaction endpoints.
- How the frontend visually represents planted/growing/ready plots.

## Suggested implementation order

No implementation begins merely because it appears in this document. When the
team is ready, the safest order is:

1. Finalize numeric balancing candidates and farm plot rules.
2. Add authoritative seed/crop/stage definitions and world state.
3. Implement buy seed → plant → grow → harvest → sell deterministically.
4. Add map stage rendering and farm plot state.
5. Implement seeded fishing duration and reward tiers.
6. Add money request/transfer transactions.
7. Add cooperative unlock proposal, agreement, contributions, and stage changes.
8. Expand mock autonomy, then Gemini prompts, against the same validated actions.
9. Run the complete loop in simulation before connecting it to physical motion.
