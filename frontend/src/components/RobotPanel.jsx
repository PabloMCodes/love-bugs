// Show each robot's health, wallet, inventory, location, and current task.
function formatLabel(value) {
    if (!value) {
        return 'Unknown';
    }

    return value
        .toLowerCase()
        .replaceAll('_', ' ')
        .replace(/^./, (character) => character.toUpperCase());
}

function getRobotStatus(robot) {
    if (!robot.physical.online) {
        return {
            label: 'Offline',
            className: 'bg-red-950 text-red-300',
        };
    }

    if (robot.physical.stopped) {
        return {
            label: 'Stopped',
            className: 'bg-red-950 text-red-300',
        };
    }

    if (robot.physical.blocked) {
        return {
            label: 'Blocked',
            className: 'bg-orange-950 text-orange-300',
        };
    }

    if (robot.task?.status === 'NAVIGATING') {
        return {
            label: 'Navigating',
            className: 'bg-sky-950 text-sky-300',
        };
    }

    if (robot.task?.status === 'ACTIVE') {
        return {
            label: formatLabel(robot.task.action),
            className: 'bg-amber-950 text-amber-300',
        };
    }

    return {
        label: 'Idle',
        className: 'bg-emerald-950 text-emerald-300',
    };
}

function RobotCard({ robot }) {
    const status = getRobotStatus(robot);
    const inventoryItems = Object.entries(robot.game.inventory ?? {})
        .map(([id, item]) => ({ id, ...item }))
        .filter((item) => item.quantity > 0);
    const battery = robot.physical.battery === null
        ? 'Unknown'
        : `${Math.round(robot.physical.battery * 100)}%`;
    const location = robot.task?.status === 'NAVIGATING'
        ? `To ${formatLabel(robot.task.location)}`
        : formatLabel(robot.game.location);
    const taskProgress = Math.round((robot.task?.progress ?? 0) * 100);

    return (
        <article className="flex h-40 flex-col overflow-hidden rounded-2xl border border-stone-800 bg-stone-900 p-4">
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
                <div>
                    <div className="flex items-center gap-2">
                        <h3 className="text-lg font-semibold">{robot.name}</h3>
                        <span className={`rounded-full px-2 py-1 text-xs font-semibold ${status.className}`}>
                            {status.label}
                        </span>
                    </div>
                    <p className="mt-1 text-xs text-stone-500">
                        {robot.id} · {formatLabel(robot.physical.tracking)}
                    </p>
                </div>
                <dl className="flex items-center gap-4 text-sm">
                    <div>
                        <dt className="text-xs text-stone-500">Location</dt>
                        <dd className="font-semibold">{location}</dd>
                    </div>
                    <div>
                        <dt className="text-xs text-stone-500">Gold</dt>
                        <dd className="font-semibold text-amber-300">{robot.game.money}</dd>
                    </div>
                    <div>
                        <dt className="text-xs text-stone-500">Battery</dt>
                        <dd className="font-semibold">{battery}</dd>
                    </div>
                </dl>
            </div>

            <div className="mt-3 grid min-h-0 flex-1 gap-3 border-t border-stone-800 pt-3 sm:grid-cols-2">
                <div>
                    <div className="flex items-center justify-between gap-3">
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-stone-400">
                            Task
                        </h4>
                        <span className="text-xs text-stone-500">
                            {robot.task ? `${taskProgress}%` : 'Idle'}
                        </span>
                    </div>

                    <p className="mt-1 text-sm">
                        {robot.task
                            ? `${formatLabel(robot.task.action)} · ${formatLabel(robot.task.status)}`
                            : 'Waiting for assignment'
                        }
                    </p>

                    {robot.task && (
                        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-stone-800">
                            <div
                                className="h-full rounded-full bg-rose-400 transition-[width]"
                                style={{ width: `${taskProgress}%` }}
                            />
                        </div>
                    )}
                </div>

                <div className="flex min-h-0 flex-col">
                    <h4 className="shrink-0 text-xs font-semibold uppercase tracking-wide text-stone-400">
                        Inventory
                    </h4>
                    {inventoryItems.length === 0 ? (
                        <p className="mt-1 text-sm text-stone-500">Empty</p>
                    ) : (
                        <div className="mt-1 flex min-h-0 flex-1 flex-wrap content-start gap-1.5 overflow-y-auto">
                            {inventoryItems.map((item) => (
                                <span
                                    key={item.id}
                                    className="rounded-md bg-stone-800 px-2 py-1 text-xs"
                                >
                                    {item.name}: {item.quantity}
                                </span>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </article>
    );
}

export default function RobotPanel({ robots }) {
    return (
        <section className="w-full shrink-0">
            <h2 className="mb-3 text-lg font-semibold">Robot Tracker</h2>
            <div className="grid gap-4 lg:grid-cols-2">
                {robots.map((robot) => (
                    <RobotCard key={robot.id} robot={robot} />
                ))}
            </div>
        </section>
    );
}
