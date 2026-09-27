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
                        className="market-parchment-card p-4 text-[#422313]"
                    >
                        <div className="flex items-start justify-between gap-4">
                            <div>
                                <h3 className="font-semibold">{item.name}</h3>
                                <p className="mt-1 text-xs text-[#805431]">
                                    {recipient
                                        ? `Recipient: ${recipient.name}`
                                        : 'No robot at the market'
                                    }
                                </p>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                                <p className="text-sm font-bold text-[#7e351f]">
                                    {item.buy_price} gold
                                </p>
                                <button
                                    type="button"
                                    disabled={!canBuy}
                                    onClick={() => onBuyItem(item.id)}
                                    className="market-action-button px-3 py-1.5 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-50"
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
