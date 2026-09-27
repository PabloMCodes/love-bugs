// Display locations from the world snapshot in its logical coordinate system.
const locationDetails = {
    homebase: { icon: '⌂', label: 'Home' },
    farm: { icon: '✦', label: 'Farm' },
    lake: { icon: '≈', label: 'Lake' },
    market: { icon: '$', label: 'Market' },
};

const robotPortraits = {
    'robot-a': '/assets/wally.png',
    'robot-b': '/assets/eve.png',
};

function TerrainBackdrop() {
    const grassTufts = [
        [7, 10], [18, 8], [32, 14], [44, 7], [58, 13], [70, 8], [91, 12],
        [29, 28], [40, 35], [62, 29], [72, 39], [92, 33], [5, 49], [38, 52],
        [56, 48], [88, 53], [33, 68], [51, 63], [72, 69], [92, 72], [8, 82],
        [24, 89], [45, 84], [63, 91], [81, 86], [95, 94],
    ];
    const flowers = [[34, 22], [58, 20], [73, 55], [47, 74], [88, 82]];

    return (
        <svg
            aria-hidden="true"
            className="absolute inset-0 h-full w-full"
            preserveAspectRatio="none"
            shapeRendering="crispEdges"
            viewBox="0 0 100 100"
        >
            <defs>
                <pattern id="grass-grid" width="8" height="8" patternUnits="userSpaceOnUse">
                    <rect width="8" height="8" fill="#4f9f38" />
                    <rect x="1" y="2" width="1" height="2" fill="#72bd49" />
                    <rect x="2" y="1" width="1" height="1" fill="#80c956" />
                    <rect x="6" y="5" width="1" height="2" fill="#2f7d2c" />
                    <rect x="5" y="6" width="1" height="1" fill="#3b8b31" />
                </pattern>
            </defs>

            <rect width="100" height="100" fill="url(#grass-grid)" />

            <g opacity="0.72">
                <rect x="0" y="18" width="18" height="25" fill="#3c91b7" />
                <rect x="2" y="16" width="13" height="29" fill="#52a8cb" />
                <rect x="5" y="19" width="12" height="23" fill="#479cc4" />
                <rect x="3" y="23" width="2" height="7" fill="#75c5db" />
                <rect x="11" y="33" width="4" height="2" fill="#75c5db" />
                <rect x="15" y="20" width="3" height="4" fill="#2f7b9f" />
            </g>

            <g fill="#9d6b35" opacity="0.88">
                <rect x="14" y="43" width="22" height="31" />
                <rect x="12" y="48" width="26" height="21" />
            </g>
            <g fill="#714721" opacity="0.62">
                <rect x="17" y="45" width="3" height="27" />
                <rect x="24" y="44" width="3" height="29" />
                <rect x="31" y="46" width="3" height="26" />
            </g>
            <g fill="#c18b46" opacity="0.72">
                <rect x="18" y="48" width="1" height="4" />
                <rect x="25" y="57" width="1" height="4" />
                <rect x="32" y="50" width="1" height="4" />
                <rect x="18" y="65" width="1" height="4" />
                <rect x="32" y="63" width="1" height="4" />
            </g>

            <g fill="#d0a05a" opacity="0.62">
                <rect x="43" y="31" width="19" height="5" />
                <rect x="57" y="28" width="6" height="8" />
                <rect x="60" y="25" width="18" height="5" />
                <rect x="74" y="22" width="7" height="8" />
                <rect x="78" y="20" width="10" height="5" />
                <rect x="35" y="34" width="11" height="5" />
                <rect x="33" y="37" width="5" height="13" />
                <rect x="30" y="47" width="6" height="13" />
            </g>
            <g fill="#efd184" opacity="0.46">
                <rect x="45" y="32" width="15" height="1" />
                <rect x="62" y="26" width="14" height="1" />
                <rect x="79" y="21" width="8" height="1" />
                <rect x="34" y="39" width="1" height="9" />
            </g>

            <g fill="#2f7429">
                {grassTufts.map(([x, y]) => (
                    <path key={`${x}-${y}`} d={`M${x} ${y + 3}H${x + 1}V${y + 1}H${x + 2}V${y + 3}H${x + 3}V${y}H${x + 4}V${y + 4}H${x}Z`} />
                ))}
            </g>
            <g fill="#f3d665">
                {flowers.map(([x, y]) => (
                    <g key={`${x}-${y}`}>
                        <rect x={x + 1} y={y} width="1" height="1" />
                        <rect x={x} y={y + 1} width="3" height="1" />
                        <rect x={x + 1} y={y + 2} width="1" height="2" fill="#26712b" />
                    </g>
                ))}
            </g>

            <g fill="#6e755f">
                <rect x="42" y="18" width="4" height="3" />
                <rect x="43" y="17" width="2" height="1" fill="#9ca083" />
                <rect x="83" y="43" width="5" height="3" />
                <rect x="84" y="42" width="3" height="1" fill="#9ca083" />
                <rect x="54" y="80" width="4" height="3" />
                <rect x="55" y="79" width="2" height="1" fill="#9ca083" />
            </g>

            <rect x="1" y="1" width="98" height="98" fill="none" stroke="#255d24" strokeWidth="2" />
            <rect x="3" y="3" width="94" height="94" fill="none" stroke="#78bd4a" strokeWidth="1" opacity="0.72" />
        </svg>
    );
}

export default function WorldMap({ world }) {
    const { map, robots } = world;

    return (
        <section className="flex h-full min-h-0 w-full flex-col">
            <h2 className="mb-3 text-lg font-semibold">World Map</h2>
            <div className="world-map-board relative min-h-0 w-full flex-1 overflow-hidden">
                <TerrainBackdrop />

                {Object.entries(map.locations).map(([id, location]) => {
                    const left = (location.x / map.width) * 100;
                    const top = (location.y / map.height) * 100;
                    const details = locationDetails[id] ?? {
                        icon: '•',
                        label: id.replaceAll('_', ' '),
                    };

                    return (
                        <div
                            key={id}
                            className="map-location-marker absolute z-10 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center"
                            style={{ left: `${left}%`, top: `${top}%` }}
                        >
                            <span className="map-location-icon flex size-10 items-center justify-center text-lg font-black">
                                {details.icon}
                            </span>
                            <span className="map-location-label px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide">
                                {details.label}
                            </span>
                        </div>
                    );
                })}

                {robots.map((robot) => {
                    const left = (robot.physical.pose.x / map.width) * 100;
                    const top = (robot.physical.pose.y / map.height) * 100;
                    const portrait = robotPortraits[robot.id];

                    return (
                        <div
                            key={robot.id}
                            className="map-robot-marker absolute z-20 flex -translate-x-1/2 -translate-y-[78%] flex-col items-center"
                            style={{ left: `${left}%`, top: `${top}%` }}
                        >
                            <span className="map-robot-portrait flex size-16 items-center justify-center overflow-hidden rounded-full">
                                {portrait ? (
                                    <img
                                        alt=""
                                        className="h-[88%] w-[88%] object-contain"
                                        src={portrait}
                                    />
                                ) : (
                                    <span className="text-xs font-bold">{robot.name}</span>
                                )}
                            </span>
                            <span className="map-robot-label px-2 py-0.5 text-[10px] font-bold">
                                {robot.name}
                            </span>
                        </div>
                    );
                })}
            </div>
        </section>
    );
}
