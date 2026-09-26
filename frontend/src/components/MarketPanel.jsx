// Show backend prices and submit buy or sell tasks for a selected robot; prices apply at execution.
import { useState } from 'react';
import BuyPanel from './BuyPanel.jsx';
import SellPanel from './SellPanel.jsx';

const marketTabs = ['buy', 'sell'];

export default function MarketPanel({
    market,
    map,
    onBuyItem,
    onSellItem,
    robots,
}) {
    const [activePanel, setActivePanel] = useState('buy');

    return (
        <section className="w-full max-w-xl">
            <h2 className="mb-3 text-lg font-semibold">Market</h2>

            <div
                className="flex w-full flex-col overflow-hidden rounded-2xl border border-stone-800 bg-stone-900"
                style={{ aspectRatio: `${map.width} / ${map.height}` }}
            >
                <div
                    className="grid grid-cols-2 border-b border-stone-800 p-3"
                    role="tablist"
                    aria-label="Market mode"
                >
                    {marketTabs.map((tab) => {
                        const isActive = activePanel === tab;

                        return (
                            <button
                                key={tab}
                                type="button"
                                role="tab"
                                aria-selected={isActive}
                                onClick={() => setActivePanel(tab)}
                                className={isActive
                                    ? 'rounded-lg bg-rose-400 px-4 py-2 text-sm font-semibold capitalize text-stone-950'
                                    : 'rounded-lg px-4 py-2 text-sm font-semibold capitalize text-stone-400 hover:bg-stone-800 hover:text-stone-100'
                                }
                            >
                                {tab}
                            </button>
                        );
                    })}
                </div>

                <div
                    className="min-h-0 flex-1 overflow-y-auto p-4"
                    role="tabpanel"
                >
                    {activePanel === 'buy' ? (
                        <BuyPanel
                            market={market}
                            onBuyItem={onBuyItem}
                            robots={robots}
                        />
                    ) : (
                        <SellPanel
                            onSellItem={onSellItem}
                            robots={robots}
                        />
                    )}
                </div>
            </div>
        </section>
    );
}
