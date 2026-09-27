// Compose the game dashboard and share world state with its components.
import { useWorld, localDemoEnabled } from './hooks/useWorld.js';
import MarketPanel from './components/MarketPanel.jsx';
import RobotPanel from './components/RobotPanel.jsx';
import WorldMap from './components/WorldMap.jsx';
import AgentChat from './components/AgentChat.jsx';
import GameControls from './components/GameControls.jsx';
import CropPanel from './components/CropPanel.jsx';
import MarketNotifications from './components/MarketNotifications.jsx';

export default function App() {
    const {
        world,
        connection,
        buyMarketItem,
        resetSession,
        startSession,
        stopSession,
    } = useWorld();

    if (connection.source !== 'backend' && !localDemoEnabled) {
        return (
            <main className="app-background min-h-dvh p-10 text-stone-100">
                <h1 className="text-3xl font-bold">Love Bugs</h1>
                <p className="mt-4">Waiting for the game backend…</p>
                <p className="mt-2 text-sm">{connection.error || 'Connecting to the live world.'}</p>
            </main>
        );
    }

    return (
        <main className="app-background h-dvh overflow-hidden px-6 py-4 text-stone-100">
            <div className="mx-auto flex h-full min-h-0 w-full max-w-[96rem] flex-col gap-4 overflow-y-auto lg:overflow-hidden">
                <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4">
                    <h1 className="section-title col-start-2 text-center text-5xl font-black leading-none sm:text-6xl">
                        Love Bugs &lt;3
                    </h1>
                    <div className="col-start-3 text-right">
                        <p className={`text-xs font-semibold ${
                            connection.connected
                                ? 'text-emerald-300'
                                : 'text-amber-300'
                        }`}>
                            {connection.connected
                                ? 'Backend connected'
                                : connection.source === 'connecting'
                                    ? 'Connecting to backend…'
                                    : connection.source === 'mock'
                                        ? 'Local demo mode'
                                        : 'Backend reconnecting…'
                            }
                        </p>
                        {connection.source === 'backend' && (
                            <p className="text-xs text-stone-300">
                                {world.mode === 'hardware' ? 'Hardware · camera-driven movement' : 'Backend simulation'}
                            </p>
                        )}
                        {connection.error && (
                            <p className="mt-1 max-w-sm text-xs text-stone-400">
                                {connection.error}
                            </p>
                        )}
                    </div>
                </div>

                <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(13rem,0.75fr)_minmax(0,3fr)_minmax(16rem,1fr)]">
                    <CropPanel farm={world.farm} robots={world.robots} />

                    <div className="flex min-h-0 flex-col gap-4">
                        <RobotPanel robots={world.robots} />

                        <GameControls
                            backendAvailable={connection.source === 'backend'}
                            game={world.game}
                            onReset={resetSession}
                            onStart={startSession}
                            onStop={stopSession}
                        />

                        <div className="grid min-h-80 w-full auto-rows-[20rem] gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-3 lg:grid-rows-1 lg:auto-rows-auto">
                            <MarketPanel
                                market={world.market}
                                game={world.game}
                                onBuyItem={buyMarketItem}
                                robots={world.robots}
                                buyDisabled={
                                    world.game.status === 'COMPLETED'
                                }
                            />
                            <div className="min-h-0 lg:col-span-2">
                                <WorldMap world={world} />
                            </div>
                        </div>
                    </div>

                    <AgentChat world={world} />
                </div>
            </div>
            <MarketNotifications world={world} />
        </main>
    );
}
