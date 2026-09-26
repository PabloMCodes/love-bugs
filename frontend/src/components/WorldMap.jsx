// Display locations from the world snapshot in its logical coordinate system.
export default function WorldMap({ world }) {
    const { map, robots } = world;
    return (
    <section className="w-full max-w-xl">
        <h2 className="mb-3 text-lg font-semibold">World Map</h2>
        <div
        className="relative w-full overflow-hidden rounded-2xl border border-green-800 bg-green-700 shadow-xl"
        style={{ aspectRatio: `${map.width} / ${map.height}` }}
        >
        {Object.entries(map.locations).map(([id, location]) => {
          const left = (location.x / map.width) * 100;
          const top = (location.y / map.height) * 100;

            return (
            <div
                key={id}
                className="absolute flex size-20 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-4 border-white bg-amber-300 text-center text-xs font-semibold capitalize text-stone-900 shadow-lg"
                style={{ left: `${left}%`, top: `${top}%` }}
            >
                {id}
            </div>
            );
        })}

        {robots.map((robot) =>{
            const left = (robot.physical.pose.x / map.width) * 100;
            const top = (robot.physical.pose.y / map.height) * 100;

            return (
                <div
                    key={robot.id}
                    className="absolute flex size-20 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-4 border-white bg-blue-300 text-center text-xs font-semibold capitalize text-stone-900 shadow-lg"
                    style={{ left: `${left}%`, top: `${top}%` }}
                >
                    {robot.name}
                </div>
            );
        })}
        </div>
    </section>
    );
}
