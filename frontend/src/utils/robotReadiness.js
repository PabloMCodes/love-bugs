export function robotInputIssues(robot, { includeStopped = true } = {}) {
    const issues = [];

    if (!robot.physical.online) {
        issues.push('offline');
    }
    if (robot.physical.tracking !== 'TRACKED' || !robot.physical.pose) {
        issues.push(
            robot.physical.tracking === 'STALE'
                ? 'stale tracking'
                : 'awaiting pose',
        );
    }
    if (robot.physical.blocked) {
        issues.push('blocked');
    }
    if (includeStopped && robot.physical.stopped) {
        issues.push('stopped');
    }

    return issues;
}

export function hardwareInputReadiness(world) {
    if (world.mode !== 'hardware') {
        return {
            ready: true,
            readyCount: world.robots.length,
            totalCount: world.robots.length,
            robots: [],
        };
    }

    const includeStopped = world.game.status === 'RUNNING';
    const robots = world.robots.map((robot) => ({
        id: robot.id,
        name: robot.name,
        issues: robotInputIssues(robot, { includeStopped }),
    }));
    const readyCount = robots.filter((robot) => robot.issues.length === 0).length;

    return {
        ready: readyCount === robots.length,
        readyCount,
        totalCount: robots.length,
        robots,
    };
}
