// Compose the game dashboard and share world state with its components.
import { useWorld } from './hooks/useWorld.js';
import WorldMap from './components/WorldMap.jsx';

export default function App() {
  const { world } = useWorld();

  return (
    <main className="flex min-h-screen items-center justify-center gap-6 bg-stone-950 px-6 py-10 text-stone-100">
      <section className="w-full max-w-xl rounded-2xl border border-stone-800 bg-stone-900 p-8">
        <p className="text-sm font-medium uppercase tracking-widest text-rose-300">Love Bugs</p>
        <h1 className="mt-3 text-3xl font-semibold">A home for your robot crew.</h1>
        <p className="mt-4 leading-relaxed text-stone-300">
          The dashboard is ready to build. Game controls and live robot updates will appear here.
        </p>
        <p className="mt-6 text-sm text-stone-400">
          Current objective: Earn {world.game.goal.target} gold ({world.game.goal.current} earned)
        </p>
      </section>
      <WorldMap world={world} />
    </main>
  );
}
