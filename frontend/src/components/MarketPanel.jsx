// Show backend prices and submit buy or sell tasks for a selected robot; prices apply at execution.
import { useState } from 'react';
import BuyPanel from './BuyPanel.jsx';
import SellPanel from './SellPanel.jsx';

const marketTabs = ['buy', 'sell'];

function CrateBackdrop() {
    const nailPositions = [
        [18, 18], [302, 18], [18, 302], [302, 302],
        [38, 52], [282, 52], [38, 268], [282, 268],
    ];

    return (
        <svg
            aria-hidden="true"
            className="absolute inset-0 h-full w-full"
            preserveAspectRatio="none"
            shapeRendering="crispEdges"
            viewBox="0 0 320 320"
        >
            <rect width="320" height="320" fill="#593016" />

            <g stroke="#3a1d0e" strokeWidth="3">
                <rect x="5" y="5" width="310" height="50" fill="#8d5424" />
                <rect x="5" y="55" width="310" height="52" fill="#754019" />
                <rect x="5" y="107" width="310" height="52" fill="#925727" />
                <rect x="5" y="159" width="310" height="52" fill="#6d3917" />
                <rect x="5" y="211" width="310" height="52" fill="#895020" />
                <rect x="5" y="263" width="310" height="52" fill="#70401d" />
            </g>

            <g fill="none" strokeLinecap="square">
                <path d="M20 14H94M116 14H214M236 14H300" stroke="#bb7837" strokeWidth="3" />
                <path d="M28 45H126M150 45H294" stroke="#542b13" strokeWidth="3" />
                <path d="M16 66H80M102 66H196M218 66H304" stroke="#a7652e" strokeWidth="3" />
                <path d="M24 96H118M142 96H248M270 96H300" stroke="#4c260f" strokeWidth="3" />
                <path d="M16 119H106M128 119H230M250 119H304" stroke="#c07b38" strokeWidth="3" />
                <path d="M28 148H156M180 148H294" stroke="#5b2c12" strokeWidth="3" />
                <path d="M18 171H82M104 171H202M224 171H302" stroke="#a6642b" strokeWidth="3" />
                <path d="M28 200H132M154 200H288" stroke="#46210e" strokeWidth="3" />
                <path d="M16 223H96M118 223H218M240 223H304" stroke="#b47131" strokeWidth="3" />
                <path d="M28 252H142M168 252H296" stroke="#51270f" strokeWidth="3" />
                <path d="M18 275H76M98 275H192M214 275H302" stroke="#a5642c" strokeWidth="3" />
                <path d="M28 304H124M148 304H286" stroke="#43200d" strokeWidth="3" />
            </g>

            <g fill="none" stroke="#3c1c0c" strokeWidth="3">
                <path d="M56 19H80V27H92V36H78V43H50V34H42V25H56Z" />
                <path d="M222 68H248V76H258V86H246V94H218V84H210V76H222Z" />
                <path d="M64 124H90V132H102V141H88V150H60V141H50V131H64Z" />
                <path d="M230 176H258V184H268V194H254V202H226V194H216V184H230Z" />
                <path d="M74 229H100V237H112V246H98V255H70V246H60V237H74Z" />
                <path d="M220 278H246V286H258V296H244V304H216V296H206V286H220Z" />
            </g>

            <g>
                <rect x="0" y="0" width="320" height="14" fill="#4a250f" />
                <rect x="0" y="306" width="320" height="14" fill="#3b1d0c" />
                <rect x="0" y="0" width="14" height="320" fill="#4b260f" />
                <rect x="306" y="0" width="14" height="320" fill="#35190a" />
                <rect x="8" y="8" width="304" height="5" fill="#aa692e" />
                <rect x="8" y="307" width="304" height="5" fill="#885021" />
            </g>

            <g fill="#25150e" stroke="#b17943" strokeWidth="1">
                {nailPositions.map(([x, y]) => (
                    <rect key={`${x}-${y}`} x={x} y={y} width="6" height="6" />
                ))}
            </g>
        </svg>
    );
}

export default function MarketPanel({
    market,
    onBuyItem,
    onSellItem,
    robots,
    buyDisabled,
    sellDisabled,
}) {
    const [activePanel, setActivePanel] = useState('buy');

    return (
        <section className="flex h-full min-h-0 w-full flex-col">
            <h2 className="mb-3 text-lg font-semibold">Market</h2>

            <div className="market-crate relative flex min-h-0 w-full flex-1 flex-col overflow-hidden">
                <CrateBackdrop />

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
