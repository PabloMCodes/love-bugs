# Frontend

The React dashboard, using JavaScript, Vite, and Tailwind CSS.
React, Vite, and Tailwind are configured with a minimal starter screen. Dashboard components and API integration remain commented placeholders.

## Run locally

Use Node 24 (recorded in `.nvmrc`). With nvm installed:

```sh
cd frontend
nvm install
nvm use
npm ci
npm run dev
```

Open the local URL printed by Vite. Without nvm, install Node 24 using your preferred Node installer. To run with a temporary Node 24 runtime instead:

```sh
cd frontend
npm exec --yes --package=node@24 -- npm ci
npm exec --yes --package=node@24 -- npm run dev
```

`npm run build` creates the production bundle in `dist/`. `npm run preview` serves that bundle locally. The starter screen runs without a backend.

## Structure

- `index.html` and `src/main.jsx`: browser entry points.
- `src/App.jsx`: dashboard layout and shared world state.
- `src/styles.css`: Tailwind and shared styles.
- `src/components/`: map, robots, game controls, tasks, market, event feed, and connection status.
- `src/hooks/useWorld.js`: current snapshot and session/revision handling.
- `src/api/`: HTTP requests and the live WebSocket connection.

Use the world model and endpoints in [api.md](../api.md). The backend owns game rules, prices, rewards, and task completion. The browser talks only to the backend and renders the returned robot list without assuming a fixed count.

Start with the world snapshot and live updates, then connect the dashboard controls. Add assets and more components when needed.
