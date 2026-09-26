function normalizeHeading(heading) {
    return (heading + 360) % 360;
}

export function movePoseToward(currentPose, target, stepDistance) {
    if (stepDistance <= 0) {
        throw new Error('stepDistance must be greater than zero.');
    }

    const deltaX = target.x - currentPose.x;
    const deltaY = target.y - currentPose.y;
    const remainingDistance = Math.hypot(deltaX, deltaY);

    if (remainingDistance === 0) {
        return {
            pose: currentPose,
            arrived: true,
        };
    }

    const heading = normalizeHeading(
        Math.atan2(deltaY, deltaX) * (180 / Math.PI),
    );

    if (remainingDistance <= stepDistance) {
        return {
            pose: {
                x: target.x,
                y: target.y,
                heading,
            },
            arrived: true,
        };
    }

    const movementRatio = stepDistance / remainingDistance;

    return {
        pose: {
            x: currentPose.x + (deltaX * movementRatio),
            y: currentPose.y + (deltaY * movementRatio),
            heading,
        },
        arrived: false,
    };
}
