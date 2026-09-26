export default function BuyPanel({ market }) {
    return (
        <div className="flex flex-col gap-3">
            {market.items.map((item) => (
                <div
                    key={item.id}
                    className="rounded-xl border border-stone-700 bg-stone-800 p-4"
                >
                    <div className="flex items-start justify-between gap-4">
                        <div>
                            <h3 className="font-semibold">{item.name}</h3>
                            <p className="mt-1 text-xs text-stone-400">
                                {item.stock === null ? 'In stock' : `${item.stock} available`}
                            </p>
                        </div>
                        <p className="shrink-0 text-sm font-semibold text-amber-300">
                            {item.buy_price} gold
                        </p>
                    </div>
                </div>
            ))}
        </div>
    );
}
