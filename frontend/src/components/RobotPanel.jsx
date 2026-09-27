// Show each robot's connection, wallet, inventory, location, and current task.
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
            className: 'bg-red-200 text-red-800',
        };
    }

    if (robot.physical.stopped) {
        return {
            label: 'Stopped',
            className: 'bg-red-200 text-red-800',
        };
    }

    if (robot.physical.blocked) {
        return {
            label: 'Blocked',
            className: 'bg-orange-200 text-orange-900',
        };
    }

    if (robot.task?.status === 'NAVIGATING') {
        return {
            label: 'Navigating',
            className: 'bg-sky-200 text-sky-800',
        };
    }

    if (robot.task?.status === 'ACTIVE') {
        return {
            label: formatLabel(robot.task.action),
            className: 'bg-amber-200 text-amber-900',
        };
    }

    return {
        label: 'Idle',
        className: 'bg-emerald-200 text-emerald-800',
    };
}

function CloudBackdrop() {
    const transitionPixels = [
        [28, 92], [48, 108], [72, 100], [96, 120], [124, 96], [148, 112],
        [176, 104], [204, 124], [232, 92], [260, 116], [288, 100], [316, 128],
        [344, 108], [372, 96], [400, 120], [428, 104], [456, 128], [484, 92],
        [512, 112], [540, 100], [568, 124], [596, 96], [624, 116], [652, 104],
    ];

    return (
        <svg
            aria-hidden="true"
            className="absolute inset-0 h-full w-full"
            preserveAspectRatio="none"
            shapeRendering="crispEdges"
            viewBox="0 0 688 160"
        >
            <rect width="688" height="160" fill="#f8fdff" />
            <path
                d="M0 72H40V64H88V68H136V76H184V64H232V56H280V68H328V76H376V64H424V70H472V80H520V72H568V64H616V76H656V84H688V160H0Z"
                fill="#e6f6fd"
            />
            <path
                d="M0 96H36V88H84V96H128V104H176V92H224V84H272V96H320V108H368V92H416V100H464V112H512V100H560V92H608V108H648V116H688V160H0Z"
                fill="#d1ecf9"
            />
            <path
                d="M0 120H48V112H96V120H152V132H208V120H264V112H320V128H376V136H432V120H488V128H544V116H600V132H648V140H688V160H0Z"
                fill="#b8def1"
            />
            <path
                d="M0 144H72V136H136V144H216V152H296V140H368V148H448V136H520V144H600V140H688V160H0Z"
                fill="#8fc3df"
            />
            <g fill="#ffffff" opacity="0.9">
                <rect x="56" y="20" width="28" height="4" />
                <rect x="84" y="16" width="44" height="4" />
                <rect x="252" y="12" width="36" height="4" />
                <rect x="288" y="16" width="24" height="4" />
                <rect x="500" y="20" width="32" height="4" />
                <rect x="600" y="36" width="24" height="4" />
            </g>
            <g fill="#9dccE5" opacity="0.72">
                {transitionPixels.map(([x, y]) => (
                    <rect key={`${x}-${y}`} x={x} y={y} width="4" height="4" />
                ))}
            </g>
            <g fill="#ffffff" opacity="0.82">
                {transitionPixels.slice(0, 18).map(([x, y]) => (
                    <rect key={`light-${x}-${y}`} x={x + 12} y={y - 12} width="4" height="4" />
                ))}
            </g>
        </svg>
    );
}

function RobotCard({ robot }) {
    const status = getRobotStatus(robot);
    const inventoryItems = Object.entries(robot.game.inventory ?? {})
        .map(([id, item]) => ({ id, ...item }))
        .filter((item) => item.quantity > 0);
    const location = robot.task?.status === 'NAVIGATING'
        ? `To ${formatLabel(robot.task.location)}`
        : formatLabel(robot.game.location);
    const taskProgress = Math.round((robot.task?.progress ?? 0) * 100);

    return (
        <article className="robot-cloud-card flex h-40 flex-col overflow-hidden px-5 py-4 text-sky-950">
            <CloudBackdrop />

            <div className="relative z-10 flex shrink-0 flex-wrap items-center justify-between gap-3">
                <div>
                    <div className="flex items-center gap-2">
                        <h3 className="text-lg font-semibold">{robot.name}</h3>
                        <span className={`rounded-full px-2 py-1 text-xs font-semibold ${status.className}`}>
                            {status.label}
                        </span>
                    </div>
                    <p className="mt-1 text-xs text-sky-700">
                        {robot.id} · {formatLabel(robot.physical.tracking)}
                    </p>
                </div>
                <dl className="flex items-center gap-4 text-sm">
                    <div>
                        <dt className="text-xs text-sky-700">Location</dt>
                        <dd className="font-semibold">{location}</dd>
                    </div>
                    <div>
                        <dt className="text-xs text-sky-700">Gold</dt>
                        <dd className="font-semibold">{robot.game.money}</dd>
                    </div>
                </dl>
            </div>

            <div className="relative z-10 mt-3 grid min-h-0 flex-1 gap-3 border-t-2 border-sky-300 pt-3 sm:grid-cols-2">
                <div>
                    <div className="flex items-center justify-between gap-3">
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-sky-700">
                            Task
                        </h4>
                        <span className="text-xs text-sky-700">
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
                        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-sky-200">
                            <div
                                className="h-full rounded-full bg-rose-400 transition-[width]"
                                style={{ width: `${taskProgress}%` }}
                            />
                        </div>
                    )}
                </div>

                <div className="flex min-h-0 flex-col">
                    <h4 className="shrink-0 text-xs font-semibold uppercase tracking-wide text-sky-700">
                        Inventory
                    </h4>
                    {inventoryItems.length === 0 ? (
                        <p className="mt-1 text-sm text-sky-700">Empty</p>
                    ) : (
                        <div className="mt-1 flex min-h-0 flex-1 flex-wrap content-start gap-1.5 overflow-y-auto">
                            {inventoryItems.map((item) => (
                                <span
                                    key={item.id}
                                    className="rounded border border-sky-300 bg-sky-100/90 px-2 py-1 text-xs text-sky-950"
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
            <h2 className="section-title mb-3 text-lg font-semibold">Robot Tracker</h2>
            <div className="grid gap-4 lg:grid-cols-2">
                {robots.map((robot) => (
                    <RobotCard key={robot.id} robot={robot} />
                ))}
            </div>
        </section>
    );
}
