// Compose the game dashboard and share world state with its components.
import { useWorld } from './hooks/useWorld.js';
import { taskCatalog } from './data/taskCatalog.js';
import MarketPanel from './components/MarketPanel.jsx';
import RobotPanel from './components/RobotPanel.jsx';
import WorldMap from './components/WorldMap.jsx';
import AgentChat from './components/AgentChat.jsx';

export default function App() {
    const harvestTask = taskCatalog.HARVEST;
    const marketLocation = taskCatalog.BUY.requiredLocation;
    const {
        world,
        connection,
        buyMarketItem,
        dispatchAgentTask,
        sellInventoryItem,
        startHarvest,
        startRobotTravel,
    } = useWorld();
    const billy = world.robots.find((robot) => robot.id === 'robot-a');
    const billyIsAtFarm = billy?.game.location === harvestTask.requiredLocation;
    const billyIsAtMarket = billy?.game.location === marketLocation;
    const billyTravelDestination = (
        billy?.task?.status === 'NAVIGATING'
            ? billy.task.location
            : null
    );
    const billyIsTravelingToFarm = (
        billyTravelDestination === harvestTask.requiredLocation
    );
    const billyIsTravelingToMarket = billyTravelDestination === marketLocation;
    const billyIsHarvesting = (
        billy?.task?.status === 'ACTIVE'
        && billy.task.action === harvestTask.action
    );
    const billyWheatQuantity = (
        billy?.game.inventory[harvestTask.reward.itemId]?.quantity ?? 0
    );
    const harvestProgress = Math.round((billy?.task?.progress ?? 0) * 100);

    return (
        <main className="h-dvh overflow-hidden bg-stone-950 px-6 py-4 text-stone-100">
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

                <div className="flex flex-wrap gap-3">
                    <button
                        type="button"
                        disabled={billyIsAtFarm || Boolean(billy?.task)}
                        onClick={() => startRobotTravel(
                            'robot-a',
                            harvestTask.requiredLocation,
                        )}
                        className="w-fit rounded-lg bg-rose-400 px-4 py-2 font-semibold text-stone-950 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {billyIsAtFarm
                            ? 'Billy arrived at Farm'
                            : billyIsTravelingToFarm
                                ? 'Billy is traveling to Farm'
                                : 'Send Billy to Farm'
                        }
                    </button>

                    <button
                        type="button"
                        disabled={
                            !billyIsAtFarm
                            || Boolean(billy?.task)
                        }
                        onClick={() => startHarvest('robot-a')}
                        className="w-fit rounded-lg bg-amber-300 px-4 py-2 font-semibold text-stone-950 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {billyIsHarvesting
                            ? `Harvesting Wheat: ${harvestProgress}%`
                            : 'Harvest Wheat'
                        }
                    </button>

                    <button
                        type="button"
                        disabled={
                            billyWheatQuantity === 0
                            || billyIsAtMarket
                            || Boolean(billy?.task)
                        }
                        onClick={() => startRobotTravel('robot-a', marketLocation)}
                        className="w-fit rounded-lg bg-sky-300 px-4 py-2 font-semibold text-stone-950 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {billyIsAtMarket
                            ? 'Billy arrived at Market'
                            : billyIsTravelingToMarket
                                ? 'Billy is traveling to Market'
                                : billyWheatQuantity === 0
                                    ? 'Harvest Wheat first'
                                    : 'Send Billy to Market'
                        }
                    </button>
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
