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

- [GAME_DESIGN.md](GAME_DESIGN.md): staged farming tycoon, fishing risk/reward,
  cooperative unlocks, money transfers, map progression, and open balance decisions.
- [GAME_PLAN.md](GAME_PLAN.md): product direction, core loop, current gaps,
  milestones, acceptance criteria, and teammate workstreams.
- [INTEGRATION.md](INTEGRATION.md): practical handoff checklist for each subsystem.
- [api.md](api.md): stable HTTP, WebSocket, and world-state contract.
- [backend/README.md](backend/README.md): backend setup and subsystem details.
- [frontend/README.md](frontend/README.md): dashboard setup and frontend structure.

The current product direction is the three-stage farming and fishing tycoon in
`GAME_DESIGN.md`. The immediate technical priority remains a reliable end-to-end
round whose state can later support those mechanics in both simulation and hardware.
