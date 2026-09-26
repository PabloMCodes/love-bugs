# Backend

The Python backend, using FastAPI and Pydantic for HTTP, WebSocket updates, and API models.
These files are commented placeholders; dependencies and implementation have not been added yet.

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
