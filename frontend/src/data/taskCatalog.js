// Define the task contract shared by frontend controls and future agent dispatch.
export const taskCatalog = Object.freeze({
    MOVE_TO: {
        action: 'MOVE_TO',
        label: 'Move to location',
        type: 'navigation',
        requiredLocation: null,
    },
    HARVEST: {
        action: 'HARVEST',
        label: 'Harvest Crop',
        type: 'activity',
        requiredLocation: 'farm',
        durationMilliseconds: 2500,
        reward: {
            itemId: 'wheat',
            name: 'Wheat',
            quantity: 3,
            sellPrice: 12,
        },
    },
    FISH: {
        action: 'FISH',
        label: 'Catch Fish',
        type: 'activity',
        requiredLocation: 'lake',
        durationMilliseconds: 2500,
        reward: {
            itemId: 'fish',
            name: 'Salmon',
            quantity: 1,
            sellPrice: 18,
        },
    },
    BUY: {
        action: 'BUY',
        label: 'Buy Item',
        type: 'transaction',
        requiredLocation: 'market',
    },
    SELL: {
        action: 'SELL',
        label: 'Sell Item',
        type: 'transaction',
        requiredLocation: 'market',
    },
    RETURN_HOME: {
        action: 'RETURN_HOME',
        label: 'Return Home',
        type: 'navigation',
        requiredLocation: 'homebase',
    },
    WAIT: {
        action: 'WAIT',
        label: 'Wait',
        type: 'idle',
        requiredLocation: null,
    },
});

export function getTaskDefinition(action) {
    return taskCatalog[action] ?? null;
}
