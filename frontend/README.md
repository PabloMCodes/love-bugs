# Frontend

The React dashboard, using JavaScript, Vite, and Tailwind CSS.
These files are commented placeholders; dependencies, build configuration, and implementation have not been added yet.

- `index.html` and `src/main.jsx`: browser entry points.
- `src/App.jsx`: dashboard layout and shared world state.
- `src/styles.css`: Tailwind and shared styles.
- `src/components/`: map, robots, game controls, tasks, market, event feed, and connection status.
- `src/hooks/useWorld.js`: current snapshot and session/revision handling.
- `src/api/`: HTTP requests and the live WebSocket connection.

Use the world model and endpoints in [api.md](../api.md). The backend owns game rules, prices, rewards, and task completion. The browser talks only to the backend and renders the returned robot list without assuming a fixed count.

Start with the world snapshot and live updates, then connect the dashboard controls. Add assets and more components when needed.
