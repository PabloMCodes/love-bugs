// Compose the game dashboard and share world state with its components.
import { useWorld } from './hooks/useWorld.js';
import MarketPanel from './components/MarketPanel.jsx';
import WorldMap from './components/WorldMap.jsx';

export default function App() {
    const { world, startRobotTravel } = useWorld();
    const billy = world.robots.find((robot) => robot.id === 'robot-a');
    const billyIsAtFarm = billy?.game.location === 'farm';
    const billyIsTraveling = billy?.task?.status === 'NAVIGATING';

    return (
        <main className="min-h-screen bg-stone-950 px-6 py-10 text-stone-100">
            <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
                <h1 className="text-3xl font-semibold">Love Bugs</h1>

                <button
                    type="button"
                    disabled={billyIsAtFarm || billyIsTraveling}
                    onClick={() => startRobotTravel('robot-a', 'farm')}
                    className="w-fit rounded-lg bg-rose-400 px-4 py-2 font-semibold text-stone-950 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    {billyIsAtFarm && 'Billy arrived at Farm'}
                    {billyIsTraveling && 'Billy is traveling to Farm'}
                    {!billyIsAtFarm && !billyIsTraveling && 'Send Billy to Farm'}
                </button>

                <div className="grid w-full items-start gap-6 lg:grid-cols-2">
                    <MarketPanel
                        market={world.market}
                        map={world.map}
                        robots={world.robots}
                    />
                    <WorldMap world={world} />
                </div>
            </div>
        </main>
    );
}
