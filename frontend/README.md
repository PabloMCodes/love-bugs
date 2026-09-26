# Frontend

The React dashboard uses JavaScript, Vite, and Tailwind CSS. It renders the
authoritative backend world, follows live WebSocket snapshots, submits movement,
collection, and sell tasks, and retains a local simulation fallback for offline demos.

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
- `src/components/`: map, robots, game controls, tasks, market, event feed, and connection status.
- `src/hooks/useWorld.js`: current snapshot and session/revision handling.
- `src/api/`: HTTP requests and the live WebSocket connection.

Use the world model and endpoints in [api.md](../api.md). The backend owns game rules, prices, rewards, and task completion. The browser talks only to the backend and renders the returned robot list without assuming a fixed count.

Start with the world snapshot and live updates, then connect the dashboard controls. Add assets and more components when needed.

## Robot conversation

The dashboard now includes a live spectator chat panel. Start the backend chat
service from `backend` with `.venv/bin/python -m uvicorn app.main:app --port 8000`.
Use **Mock demo → Start chat** to test without credentials, or **Gemini agents**
to use the backend's exported `GOOGLE_API_KEY`. The browser never receives the key.

Messages are based on the current world and the robots' recent conversation.
While chat is running, new movement, harvest, fishing, and sell proposals are
submitted to the backend automatically. Buying remains unavailable until its
backend transaction is implemented.
Start/Pause controls the discussion loop. Pausing permits the current round to
finish. Scroll up to read history; automatic scrolling resumes when you return to
the bottom. The panel reconnects automatically and restores the shared history.

Set `VITE_API_BASE_URL` in a local `.env` if the backend is elsewhere; restart Vite
afterward. The default is `http://localhost:8000`. Allow the frontend's exact origin
through backend `FRONTEND_ORIGINS` if Vite runs on a different port. Use one browser
as the chat operator; other spectators only need to open the page.
