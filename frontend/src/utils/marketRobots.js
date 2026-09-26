export function sortRobotsByMarketAvailability(robots) {
    return [...robots].sort((firstRobot, secondRobot) => {
        const firstIsAtMarket = firstRobot.game.location === 'market';
        const secondIsAtMarket = secondRobot.game.location === 'market';

        return Number(secondIsAtMarket) - Number(firstIsAtMarket);
    });
}

export function getMarketRobot(robots) {
    return sortRobotsByMarketAvailability(robots).find(
        (robot) => robot.game.location === 'market',
    ) ?? null;
}
