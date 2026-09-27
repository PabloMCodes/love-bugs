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

export default function WorldMap({ world }) {
    const { map, robots } = world;

    return (
        <section className="flex h-full min-h-0 w-full flex-col">
            <h2 className="mb-3 text-lg font-semibold">World Map</h2>
            <div className="world-map-board relative min-h-0 w-full flex-1 overflow-hidden">
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
