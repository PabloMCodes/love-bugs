// Reserve the farm-status queue for authoritative crop plots and growth timers.
export default function CropPanel() {
    return (
        <section className="flex h-full min-h-0 w-full flex-col">
            <h2 className="section-title mb-3 text-lg font-semibold">Crop Queue</h2>

            <div className="market-crate flex min-h-0 w-full flex-1 flex-col overflow-hidden p-5">
                <div className="mb-3 flex shrink-0 items-center justify-between gap-3 text-amber-50">
                    <span className="text-xs font-bold uppercase tracking-wide">Planting order</span>
                    <span className="market-stage-badge px-2 py-1 text-[10px] font-bold uppercase tracking-wide">
                        0 active
                    </span>
                </div>

                <div className="market-scrollbar min-h-0 flex-1 overflow-y-auto pr-1">
                    <div className="market-parchment-card p-4 text-[#422313]">
                        <h3 className="font-semibold">Queue empty</h3>
                        <p className="mt-1 text-xs text-[#805431]">
                            Planted crops will appear here in the order they are growing.
                        </p>
                    </div>
                </div>
            </div>
        </section>
    );
}
