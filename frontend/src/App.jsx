// Compose the game dashboard and share world state with its components.
import { useWorld } from './hooks/useWorld.js';
import MarketPanel from './components/MarketPanel.jsx';
import WorldMap from './components/WorldMap.jsx';

export default function App() {
  const { world } = useWorld();

  return (
    <main className="min-h-screen bg-stone-950 px-6 py-10 text-stone-100">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <h1 className="text-3xl font-semibold">Love Bugs</h1>

        <div className="grid w-full items-start gap-6 lg:grid-cols-2">
          <MarketPanel market={world.market} map={world.map} />
          <WorldMap world={world} />
        </div>
      </div>
    </main>
  );
}
