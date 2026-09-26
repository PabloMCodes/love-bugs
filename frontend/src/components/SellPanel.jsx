export default function SellPanel({ robots }) {
    const robotsByAvailability = [...robots].sort((firstRobot, secondRobot) => {
        const firstIsAtMarket = firstRobot.game.location === 'market';
        const secondIsAtMarket = secondRobot.game.location === 'market';

        return Number(secondIsAtMarket) - Number(firstIsAtMarket);
    });

    return (
        <div className="flex flex-col gap-3">
            {robotsByAvailability.map((robot) => {
                const isAtMarket = robot.game.location === 'market';
                const inventoryItems = Object.entries(robot.game.inventory ?? {})
                    .map(([id, item]) => ({ id, ...item }))
                    .filter((item) => item.quantity > 0);

                return (
                    <section
                        key={robot.id}
                        aria-disabled={!isAtMarket}
                        className={`rounded-xl border p-4 ${
                            isAtMarket
                                ? 'border-stone-700 bg-stone-800'
                                : 'border-stone-800 bg-stone-900 opacity-40 grayscale'
                        }`}
                    >
                        <div className="flex items-center justify-between gap-4">
                            <h3 className="font-semibold">{robot.name}</h3>
                            <span className="text-xs font-semibold text-stone-400">
                                {isAtMarket ? 'At market' : `At ${robot.game.location}`}
                            </span>
                        </div>

                        {inventoryItems.length === 0 ? (
                            <p className="mt-3 text-sm text-stone-400">
                                Inventory is empty.
                            </p>
                        ) : (
                            <div className="mt-3 flex flex-col gap-2">
                                {inventoryItems.map((item) => (
                                    <div
                                        key={item.id}
                                        className="flex items-center justify-between gap-4 rounded-lg border border-stone-700 p-3"
                                    >
                                        <div>
                                            <h4 className="text-sm font-semibold">{item.name}</h4>
                                            <p className="text-xs text-stone-400">
                                                Quantity: {item.quantity}
                                            </p>
                                        </div>
                                        <p className="shrink-0 text-sm font-semibold text-amber-300">
                                            {item.sell_price} gold each
                                        </p>
                                    </div>
                                ))}
                            </div>
                        )}

                        {!isAtMarket && (
                            <p className="mt-3 text-xs font-semibold text-stone-500">
                                Move {robot.name} to the market to access these items.
                            </p>
                        )}
                    </section>
                );
            })}
        </div>
    );
}
