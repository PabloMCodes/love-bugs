// Show backend prices and submit seed purchases for the robot currently at the market.
import BuyPanel from './BuyPanel.jsx';

export default function MarketPanel({
    market,
    onBuyItem,
    robots,
    buyDisabled,
    game,
}) {
    return (
        <section className="flex h-full min-h-0 w-full flex-col">
            <h2 className="section-title mb-3 text-lg font-semibold">Market</h2>

            <div className="market-crate relative flex min-h-0 w-full flex-1 flex-col overflow-hidden">
                <div
                    className="market-scrollbar relative z-10 min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-4 pb-5 pt-5 [scrollbar-gutter:stable]"
                >
                    <BuyPanel
                        disabled={buyDisabled}
                        market={market}
                        onBuyItem={onBuyItem}
                        robots={robots}
                        stage={game.stage}
                    />
                </div>
            </div>
        </section>
    );
}
