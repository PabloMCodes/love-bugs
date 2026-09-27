# Frontend

The React dashboard uses JavaScript, Vite, and Tailwind CSS. It renders the
authoritative backend world, follows live WebSocket snapshots, provides game
lifecycle controls and seed purchases, and retains a local simulation fallback
for offline demos. Autonomous movement, collection, and sales remain backend-owned.

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

`npm run build` creates the production bundle in `dist/`. `npm run preview` serves that bundle locally. The dashboard runs in local demo mode without a backend.

## Structure

- `index.html` and `src/main.jsx`: browser entry points.
- `src/App.jsx`: dashboard layout and shared world state.
- `src/styles.css`: Tailwind and shared styles.
- `src/components/`: Crop Queue, market, map, robot tracker, game controls,
  transaction notifications, and spectator conversation.
- `src/hooks/useWorld.js`: current snapshot and session/revision handling.
- `src/api/`: HTTP requests and the live WebSocket connection.

Use the stable schema-version-2 world model and endpoints in [api.md](../api.md), and follow
the frontend section of the [integration checklist](../INTEGRATION.md). The shared
objective and UI milestones are tracked in [GAME_PLAN.md](../GAME_PLAN.md). The backend
owns game rules, prices, rewards, and task completion. The browser talks only to
the backend and renders the returned robot list without assuming a fixed count.

The current wide-screen layout keeps the Crop Queue on the far left, robot state
and game progress in the center, and Robot Conversation on the far right. Market
and the wider World Map share the lower center row.

## Current gameplay UI

- **Crop Queue:** derives nonempty entries from `world.farm.plots`, showing ready
  crops first and growing crops ordered by `ready_at`; each growing card animates
  a countdown and progress bar derived from authoritative backend timestamps.
- **Market:** purchase-only list of all three seeds with backend-enforced stage locks.
- **Transactions:** successful purchases and sales create small parchment notices
  on a transparent right-edge overlay. The notices are derived from paired
  `inventory_updated` and `gold_updated` events and disappear after five seconds.
- **Robot Conversation:** smoothly follows new accepted/waiting agent messages;
  manual scrolling away from the bottom pauses auto-follow.
- **Game controls:** start, stop, reset, Farm Stage, and combined-gold progress.

The browser animates crop progress from timestamps but never decides that a crop
is ready. The next frontend crop milestone is later-crop artwork after carrot and
pumpkin definitions and balance values are finalized.

## Robot conversation

The dashboard includes a read-only live spectator panel. Start the backend from
`backend` with `.venv/bin/python -m uvicorn app.main:app --port 8000`, configure
`AUTONOMY_PROVIDER=mock` or `gemini`, and set `AUTONOMY_ENABLED=true` when the
backend should plan. Start and stop the game with the session controls; there are
no browser chat-provider or planning controls. The browser never receives the
Gemini key.

Messages reflect accepted or waiting backend decisions. Scroll up to read history;
automatic smooth scrolling resumes when you return to the bottom. The panel
reconnects automatically and restores the shared bounded history.

Set `VITE_API_BASE_URL` in a local `.env` if the backend is elsewhere; restart Vite
afterward. The default is `http://localhost:8000`. Allow the frontend's exact origin
through backend `FRONTEND_ORIGINS` if Vite runs on a different port.

When the backend starts with `AUTONOMY_ENABLED=true`, it owns planning and keeps
playing if every browser closes. Start the game through the UI or
`POST /game/start`.
