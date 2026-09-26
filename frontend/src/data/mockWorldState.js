export const mockWorldState = {
    schema_version: 1,
    session_id: 'demo-session-001',
    revision: 1,
    updated_at: '2026-09-26T13:00:00.000Z',
    mode: 'simulation',
    game: {
        status: 'READY',
        goal: {
            type: 'earn_gold',
            target: 500,
            current: 80,
        },
    },
    map: {
        width: 100,
        height: 100,
        locations: {
            homebase: { x: 50, y: 30 },
            farm: { x: 20, y: 50 },
            lake: { x: 12, y: 30 },
            market: { x: 80, y: 25 },
        },
    },
    robots: [
        {
            id: 'robot-a',
            name: 'Billy',
            physical: {
                online: true,
                pose: { x: 12, y: 30, heading: 0 },
                pose_updated_at: '2026-09-26T13:00:00.000Z',
                tracking: 'TRACKED',
                battery: 0.82,
                blocked: false,
                stopped: false,
            },
            game: {
                location: 'lake',
                money: 40,
                inventory: {
                    fish: {
                        name: 'Salmon',
                        quantity: 2,
                        sell_price: 18,
                    },
                    berries: {
                        name: 'Wild Berries',
                        quantity: 4,
                        sell_price: 9,
                    },
                },
            },
            task: null,
        },
        {
            id: 'robot-b',
            name: 'Milo',
            physical: {
                online: true,
                pose: { x: 80, y: 25, heading: 180 },
                pose_updated_at: '2026-09-26T13:00:00.000Z',
                tracking: 'TRACKED',
                battery: 0.94,
                blocked: false,
                stopped: false,
            },
            game: {
                location: 'market',
                money: 40,
                inventory: {
                    crop: {
                        name: 'Wheat',
                        quantity: 3,
                        sell_price: 12,
                    },
                    corn: {
                        name: 'Corn',
                        quantity: 1,
                        sell_price: 15,
                    },
                    wood: {
                        name: 'Wood',
                        quantity: 6,
                        sell_price: 6,
                    },
                },
            },
            task: null,
        },
    ],
    market: {
        items: [
            {
                id: 'seeds',
                name: 'Wheat Seeds',
                buy_price: 5,
                stock: null,
            },
            {
                id: 'corn_seeds',
                name: 'Corn Seeds',
                buy_price: 8,
                stock: null,
            },
            {
                id: 'tool_upgrade',
                name: 'Tool Upgrade',
                buy_price: 40,
                stock: 1,
            },
        ],
    },
    events: [
        {
            id: 'event-001',
            timestamp: '2026-09-26T13:00:00.000Z',
            type: 'game_ready',
            robot_id: null,
            task_id: null,
            message: 'Billy is at the lake and Milo is at the market.',
            data: {},
        },
    ],
};
