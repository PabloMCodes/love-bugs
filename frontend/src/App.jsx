// Compose the game dashboard and share world state with its components.
import { useWorld } from './hooks/useWorld.js';
import MarketPanel from './components/MarketPanel.jsx';
import RobotPanel from './components/RobotPanel.jsx';
import WorldMap from './components/WorldMap.jsx';
import AgentChat from './components/AgentChat.jsx';

export default function App() {
    const {
        world,
        connection,
        buyMarketItem,
        dispatchAgentTask,
        sellInventoryItem,
    } = useWorld();

    return (
        <main className="app-background h-dvh overflow-hidden px-6 py-4 text-stone-100">
            <div className="mx-auto flex h-full min-h-0 w-full max-w-6xl flex-col gap-4 overflow-y-auto lg:overflow-hidden">
                <div className="flex items-center justify-between gap-4">
                    <h1 className="text-3xl font-semibold">Love Bugs</h1>
                    <div className="text-right">
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
                        {connection.error && (
                            <p className="mt-1 max-w-sm text-xs text-stone-400">
                                {connection.error}
                            </p>
                        )}
                    </div>
                </div>

                <RobotPanel robots={world.robots} />

                <div className="grid min-h-80 w-full auto-rows-[20rem] gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-3 lg:grid-rows-1 lg:auto-rows-auto">
                    <MarketPanel
                        market={world.market}
                        onBuyItem={buyMarketItem}
                        onSellItem={sellInventoryItem}
                        robots={world.robots}
                        buyDisabled={
                            world.game.status === 'COMPLETED'
                        }
                        sellDisabled={world.game.status === 'COMPLETED'}
                    />
                    <WorldMap world={world} />
                    <AgentChat
                        onTaskProposal={dispatchAgentTask}
                        world={world}
                    />
                </div>
            </div>
        </main>
    );
}
