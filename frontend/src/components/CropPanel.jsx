// Reserve the farm-status surface for authoritative crop plots and growth timers.
export default function CropPanel() {
    return (
        <section className="flex h-full min-h-0 w-full flex-col">
            <h2 className="section-title mb-3 text-lg font-semibold">Growing Crops</h2>

            <div className="market-crate flex min-h-0 w-full flex-1 flex-col overflow-hidden p-5">
                <div className="market-parchment-card p-4 text-[#422313]">
                    <h3 className="font-semibold">No crops growing</h3>
                    <p className="mt-1 text-xs text-[#805431]">
                        Planted crops and their growth timers will appear here.
                    </p>
                </div>
            </div>
        </section>
    );
}
