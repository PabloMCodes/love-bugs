// Show backend prices and submit buy or sell tasks for a selected robot; prices apply at execution.

export default function MarketPanel({ market, map }) {
  return (
    <section className="w-full max-w-xl">
      <h2 className="mb-3 text-lg font-semibold">Market</h2>
      <div
        className="w-full overflow-hidden rounded-2xl border border-stone-800 bg-stone-900"
        style={{ aspectRatio: `${map.width} / ${map.height}` }}
      >
        <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
          {market.items.map((item) => (
            <div
              key={item.id}
              className="shrink-0 rounded-xl border border-stone-700 bg-stone-800 p-4"
            >
              <h3 className="font-semibold">{item.name}</h3>
              <div className="mt-3 space-y-1 text-sm text-stone-300">
                <p>Buy: {item.buy_price ?? 'Not available'}</p>
                <p>Sell: {item.sell_price ?? 'Not available'}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
