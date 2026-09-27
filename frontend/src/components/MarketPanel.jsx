// Show backend prices and submit buy or sell tasks for a selected robot; prices apply at execution.
import { useState } from 'react';
import BuyPanel from './BuyPanel.jsx';
import SellPanel from './SellPanel.jsx';

const marketTabs = ['buy', 'sell'];

export default function MarketPanel({
    market,
    onBuyItem,
    onSellItem,
    robots,
    buyDisabled,
    game,
    sellDisabled,
}) {
    const [activePanel, setActivePanel] = useState('buy');

    return (
        <section className="flex h-full min-h-0 w-full flex-col">
            <h2 className="section-title mb-3 text-lg font-semibold">Market</h2>

            <div className="market-crate relative flex min-h-0 w-full flex-1 flex-col overflow-hidden">
                <div
                    className="relative z-10 grid shrink-0 grid-cols-2 gap-3 px-5 pb-2 pt-5"
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
                                className={`market-paper-tab px-4 py-2 text-sm font-bold capitalize ${
                                    isActive ? 'is-active' : ''
                                }`}
                            >
                                {tab}
                            </button>
                        );
                    })}
                </div>

                <div
                    className="market-scrollbar relative z-10 min-h-0 flex-1 overflow-y-auto px-5 pb-5 pt-2"
                    role="tabpanel"
                >
                    {activePanel === 'buy' ? (
                        <BuyPanel
                            disabled={buyDisabled}
                            market={market}
                            onBuyItem={onBuyItem}
                            robots={robots}
                            stage={game.stage}
                        />
                    ) : (
                        <SellPanel
                            disabled={sellDisabled}
                            onSellItem={onSellItem}
                            robots={robots}
                        />
                    )}
                </div>
            </div>
        </section>
    );
}
