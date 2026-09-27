import { useEffect, useState } from 'react';

// Render the backend-owned farm plots as a queue without owning crop state locally.
function displayTime(timestamp) {
    if (!timestamp) {
        return null;
    }

    return new Intl.DateTimeFormat([], {
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
    }).format(new Date(timestamp));
}

function growthProgress(plot, now) {
    const plantedAt = Date.parse(plot.planted_at);
    const readyAt = Date.parse(plot.ready_at);
    if (!Number.isFinite(plantedAt) || !Number.isFinite(readyAt) || readyAt <= plantedAt) {
        return { percent: 0, remainingSeconds: null };
    }

    return {
        percent: Math.min(100, Math.max(0, ((now - plantedAt) / (readyAt - plantedAt)) * 100)),
        remainingSeconds: Math.max(0, Math.ceil((readyAt - now) / 1000)),
    };
}

export default function CropPanel({ farm, robots }) {
    const [now, setNow] = useState(Date.now());
    const hasGrowingCrop = farm.plots.some((plot) => plot.status === 'GROWING');

    useEffect(() => {
        if (!hasGrowingCrop) {
            return undefined;
        }

        setNow(Date.now());
        const timer = window.setInterval(() => setNow(Date.now()), 250);
        return () => window.clearInterval(timer);
    }, [hasGrowingCrop]);

    const cropNames = new Map(farm.crops.map((crop) => [crop.id, crop.name]));
    const robotNames = new Map(robots.map((robot) => [robot.id, robot.name]));
    const activePlots = farm.plots
        .filter((plot) => plot.status !== 'EMPTY')
        .sort((first, second) => {
            if (first.status !== second.status) {
                return first.status === 'READY' ? -1 : 1;
            }
            return (first.ready_at ?? '').localeCompare(second.ready_at ?? '');
        });
    const emptyPlotCount = farm.plots.length - activePlots.length;

    return (
        <section className="flex h-full min-h-0 w-full flex-col">
            <h2 className="section-title mb-3 text-lg font-semibold">Crop Queue</h2>

            <div className="market-crate flex min-h-0 w-full flex-1 flex-col overflow-hidden p-5">
                <div className="mb-3 flex shrink-0 items-center justify-between gap-3 text-amber-50">
                    <span className="text-xs font-bold uppercase tracking-wide">Planting order</span>
                    <span className="market-stage-badge px-2 py-1 text-[10px] font-bold uppercase tracking-wide">
                        {activePlots.length} active
                    </span>
                </div>

                <div className="market-scrollbar min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
                    {activePlots.length === 0 ? (
                        <div className="market-parchment-card p-4 text-[#422313]">
                            <h3 className="font-semibold">Queue empty</h3>
                            <p className="mt-1 text-xs text-[#805431]">
                                {emptyPlotCount} plots are ready for planting.
                            </p>
                        </div>
                    ) : activePlots.map((plot) => {
                        const growth = growthProgress(plot, now);
                        return (
                            <article
                                className="market-parchment-card p-4 text-[#422313]"
                                key={plot.id}
                            >
                                <div className="flex items-start justify-between gap-2">
                                    <div>
                                        <h3 className="font-semibold">
                                            {cropNames.get(plot.crop_id) ?? plot.crop_id}
                                        </h3>
                                        <p className="mt-0.5 text-[10px] font-bold uppercase tracking-wide text-[#805431]">
                                            {plot.id.replace('-', ' ')}
                                        </p>
                                    </div>
                                    <span className="market-stage-badge px-2 py-1 text-[10px] font-bold uppercase tracking-wide">
                                        {plot.status}
                                    </span>
                                </div>
                                <p className="mt-3 text-xs text-[#805431]">
                                    Planted by {robotNames.get(plot.planted_by) ?? plot.planted_by}
                                </p>
                                <p className="mt-1 text-xs font-semibold text-[#63391f]">
                                    {plot.status === 'READY'
                                        ? 'Ready to harvest'
                                        : growth.remainingSeconds === 0
                                            ? 'Ready any moment'
                                            : `Ready in ${growth.remainingSeconds}s at ${displayTime(plot.ready_at)}`}
                                </p>
                                {plot.status === 'GROWING' && (
                                    <div
                                        aria-label={`${cropNames.get(plot.crop_id) ?? 'Crop'} growth`}
                                        aria-valuemax="100"
                                        aria-valuemin="0"
                                        aria-valuenow={Math.round(growth.percent)}
                                        className="mt-2 h-2 overflow-hidden rounded-sm border border-[#805431] bg-[#c89a57]"
                                        role="progressbar"
                                    >
                                        <div
                                            className="h-full bg-[#5f8b3d] transition-[width] duration-300"
                                            style={{ width: `${growth.percent}%` }}
                                        />
                                    </div>
                                )}
                            </article>
                        );
                    })}
                </div>

                <p className="mt-3 shrink-0 text-center text-[10px] font-bold uppercase tracking-wide text-amber-50">
                    {emptyPlotCount} of {farm.plots.length} plots available
                </p>
            </div>
        </section>
    );
}
