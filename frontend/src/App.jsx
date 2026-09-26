// Compose the game dashboard and share world state with its components.
import { useWorld } from './hooks/useWorld.js';
import MarketPanel from './components/MarketPanel.jsx';
import WorldMap from './components/WorldMap.jsx';

export default function App() {
    const {
        world,
        buyMarketItem,
        sellInventoryItem,
        startHarvest,
        startRobotTravel,
    } = useWorld();
    const billy = world.robots.find((robot) => robot.id === 'robot-a');
    const billyIsAtFarm = billy?.game.location === 'farm';
    const billyIsAtMarket = billy?.game.location === 'market';
    const billyTravelDestination = (
        billy?.task?.status === 'NAVIGATING'
            ? billy.task.location
            : null
    );
    const billyIsTravelingToFarm = billyTravelDestination === 'farm';
    const billyIsTravelingToMarket = billyTravelDestination === 'market';
    const billyIsHarvesting = (
        billy?.task?.status === 'ACTIVE'
        && billy.task.action === 'HARVEST'
    );
    const billyWheatQuantity = billy?.game.inventory.crop?.quantity ?? 0;
    const harvestProgress = Math.round((billy?.task?.progress ?? 0) * 100);

    return (
        <main className="min-h-screen bg-stone-950 px-6 py-10 text-stone-100">
            <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
                <h1 className="text-3xl font-semibold">Love Bugs</h1>

                <div className="flex flex-wrap gap-3">
                    <button
                        type="button"
                        disabled={billyIsAtFarm || Boolean(billy?.task)}
                        onClick={() => startRobotTravel('robot-a', 'farm')}
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
                        disabled={!billyIsAtFarm || Boolean(billy?.task)}
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
                        onClick={() => startRobotTravel('robot-a', 'market')}
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

                <div className="grid w-full items-start gap-6 lg:grid-cols-2">
                    <MarketPanel
                        market={world.market}
                        map={world.map}
                        onBuyItem={buyMarketItem}
                        onSellItem={sellInventoryItem}
                        robots={world.robots}
                    />
                    <WorldMap world={world} />
                </div>
            </div>
        </main>
    );
}
