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
            target: 200,
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
            name: 'Wall-y',
            physical: {
                online: true,
                pose: { x: 50, y: 30, heading: 0 },
                pose_updated_at: '2026-09-26T13:00:00.000Z',
                tracking: 'TRACKED',
                battery: 0.82,
                blocked: false,
                stopped: false,
            },
            game: {
                location: 'homebase',
                money: 40,
                inventory: {},
            },
            task: null,
        },
        {
            id: 'robot-b',
            name: 'Eeva',
            physical: {
                online: true,
                pose: { x: 50, y: 30, heading: 180 },
                pose_updated_at: '2026-09-26T13:00:00.000Z',
                tracking: 'TRACKED',
                battery: 0.94,
                blocked: false,
                stopped: false,
            },
            game: {
                location: 'homebase',
                money: 40,
                inventory: {},
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
                id: 'carrot_seeds',
                name: 'Carrot Seeds',
                buy_price: 10,
                stock: null,
            },
            {
                id: 'pumpkin_seeds',
                name: 'Pumpkin Seeds',
                buy_price: 20,
                stock: null,
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
            message: 'Wall-y and Eeva are at homebase, ready to begin.',
            data: {},
        },
    ],
};
