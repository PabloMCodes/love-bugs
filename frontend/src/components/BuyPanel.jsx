import { getMarketRobot } from '../utils/marketRobots.js';

export default function BuyPanel({ disabled = false, market, onBuyItem, robots }) {
    const recipient = getMarketRobot(robots);

    return (
        <div className="flex flex-col gap-3">
            {market.items.map((item) => {
                const canBuy = Boolean(
                    !disabled
                    && recipient
                    && recipient.physical.online
                    && !recipient.physical.stopped
                    && !recipient.task
                    && recipient.game.money >= item.buy_price
                    && item.stock !== 0,
                );

                return (
                    <div
                        key={item.id}
                        className="rounded-xl border border-stone-700 bg-stone-800 p-4"
                    >
                        <div className="flex items-start justify-between gap-4">
                            <div>
                                <h3 className="font-semibold">{item.name}</h3>
                                <p className="mt-1 text-xs text-stone-400">
                                    {recipient
                                        ? `Recipient: ${recipient.name}`
                                        : 'No robot at the market'
                                    }
                                </p>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                                <p className="text-sm font-semibold text-amber-300">
                                    {item.buy_price} gold
                                </p>
                                <button
                                    type="button"
                                    disabled={!canBuy}
                                    onClick={() => onBuyItem(item.id)}
                                    className="rounded-md bg-sky-300 px-3 py-1 text-xs font-semibold text-stone-950 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                    Buy
                                </button>
                            </div>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
