// Own the current world snapshot, connection status, session changes, and revision checks across REST and WebSocket updates.
import { useEffect, useState } from 'react';
import { mockWorldState } from '../data/mockWorldState.js';
import { movePoseToward } from '../simulation/movement.js';
import { getMarketRobot } from '../utils/marketRobots.js';

const simulationStepDistance = 5;
const simulationTickMilliseconds = 250;
const harvestProgressPerTick = 0.1;
const wheatHarvestQuantity = 3;

export function useWorld() {
    const [world, setWorld] = useState(mockWorldState);

    useEffect(() => {
        const simulationTimer = window.setInterval(() => {
            setWorld((currentWorld) => {
                const simulatedRobots = currentWorld.robots.filter(
                    (robot) => (
                        robot.task?.status === 'NAVIGATING'
                        || (
                            robot.task?.status === 'ACTIVE'
                            && robot.task.action === 'HARVEST'
                        )
                    ),
                );

                if (simulatedRobots.length === 0) {
                    return currentWorld;
                }

                const updatedAt = new Date().toISOString();
                const simulationEvents = [];

                const robots = currentWorld.robots.map((robot) => {
                    if (robot.task?.status === 'NAVIGATING' && robot.physical.pose) {
                        const target = currentWorld.map.locations[robot.task.location];

                        if (!target) {
                            return robot;
                        }

                        const movement = movePoseToward(
                            robot.physical.pose,
                            target,
                            simulationStepDistance,
                        );

                        if (movement.arrived) {
                            simulationEvents.push({
                                id: `event-${robot.task.id}-arrived`,
                                timestamp: updatedAt,
                                type: 'robot_arrived',
                                robot_id: robot.id,
                                task_id: robot.task.id,
                                message: `${robot.name} arrived at ${robot.task.location}.`,
                                data: {},
                            });
                        }

                        return {
                            ...robot,
                            physical: {
                                ...robot.physical,
                                pose: movement.pose,
                                pose_updated_at: updatedAt,
                            },
                            game: {
                                ...robot.game,
                                location: movement.arrived ? robot.task.location : null,
                            },
                            task: movement.arrived ? null : robot.task,
                        };
                    }

                    if (
                        robot.task?.status === 'ACTIVE'
                        && robot.task.action === 'HARVEST'
                    ) {
                        const progress = Math.min(
                            1,
                            robot.task.progress + harvestProgressPerTick,
                        );

                        if (progress < 1) {
                            return {
                                ...robot,
                                task: {
                                    ...robot.task,
                                    progress,
                                },
                            };
                        }

                        const currentWheat = robot.game.inventory.crop;
                        const wheatQuantity = (
                            currentWheat?.quantity ?? 0
                        ) + wheatHarvestQuantity;

                        simulationEvents.push(
                            {
                                id: `event-${robot.task.id}-inventory`,
                                timestamp: updatedAt,
                                type: 'inventory_updated',
                                robot_id: robot.id,
                                task_id: robot.task.id,
                                message: `${robot.name} collected ${wheatHarvestQuantity} Wheat.`,
                                data: {
                                    item: 'crop',
                                    quantity: wheatHarvestQuantity,
                                    total_quantity: wheatQuantity,
                                },
                            },
                            {
                                id: `event-${robot.task.id}-completed`,
                                timestamp: updatedAt,
                                type: 'task_completed',
                                robot_id: robot.id,
                                task_id: robot.task.id,
                                message: `${robot.name} completed harvesting.`,
                                data: {},
                            },
                        );

                        return {
                            ...robot,
                            game: {
                                ...robot.game,
                                inventory: {
                                    ...robot.game.inventory,
                                    crop: {
                                        name: currentWheat?.name ?? 'Wheat',
                                        quantity: wheatQuantity,
                                        sell_price: currentWheat?.sell_price ?? 12,
                                    },
                                },
                            },
                            task: null,
                        };
                    }

                    return robot;
                });

                return {
                    ...currentWorld,
                    revision: currentWorld.revision + 1,
                    updated_at: updatedAt,
                    robots,
                    events: [
                        ...currentWorld.events,
                        ...simulationEvents,
                    ].slice(-100),
                };
            });
        }, simulationTickMilliseconds);

        return () => window.clearInterval(simulationTimer);
    }, []);

    function startRobotTravel(robotId, destinationId) {
        setWorld((currentWorld) => {
            const target = currentWorld.map.locations[destinationId];

            if (!target) {
                return currentWorld;
            }

            const updatedAt = new Date().toISOString();
            const taskId = `task-${currentWorld.revision + 1}`;
            let stateChanged = false;

            const robots = currentWorld.robots.map((robot) => {
                if (
                    robot.id !== robotId
                    || !robot.physical.pose
                    || !robot.physical.online
                    || robot.task
                    || robot.physical.stopped
                ) {
                    return robot;
                }

                stateChanged = true;

                return {
                    ...robot,
                    game: {
                        ...robot.game,
                        location: null,
                    },
                    task: {
                        id: taskId,
                        robot_id: robot.id,
                        action: 'MOVE_TO',
                        location: destinationId,
                        status: 'NAVIGATING',
                        progress: 0,
                        parameters: {},
                        reason: `Travel to ${destinationId}.`,
                        error: null,
                    },
                };
            });

            if (!stateChanged) {
                return currentWorld;
            }

            return {
                ...currentWorld,
                revision: currentWorld.revision + 1,
                updated_at: updatedAt,
                game: {
                    ...currentWorld.game,
                    status: 'RUNNING',
                },
                robots,
                events: [
                    ...currentWorld.events,
                    {
                        id: `event-${taskId}-assigned`,
                        timestamp: updatedAt,
                        type: 'task_assigned',
                        robot_id: robotId,
                        task_id: taskId,
                        message: `Robot assigned to travel to ${destinationId}.`,
                        data: {},
                    },
                ].slice(-100),
            };
        });
    }

    function startHarvest(robotId) {
        setWorld((currentWorld) => {
            const updatedAt = new Date().toISOString();
            const taskId = `task-${currentWorld.revision + 1}`;
            let harvestingRobot = null;

            const robots = currentWorld.robots.map((robot) => {
                if (
                    robot.id !== robotId
                    || robot.game.location !== 'farm'
                    || !robot.physical.online
                    || robot.physical.stopped
                    || robot.task
                ) {
                    return robot;
                }

                harvestingRobot = robot;

                return {
                    ...robot,
                    task: {
                        id: taskId,
                        robot_id: robot.id,
                        action: 'HARVEST',
                        location: 'farm',
                        status: 'ACTIVE',
                        progress: 0,
                        parameters: { item: 'crop' },
                        reason: 'Harvest Wheat to sell at the market.',
                        error: null,
                    },
                };
            });

            if (!harvestingRobot) {
                return currentWorld;
            }

            return {
                ...currentWorld,
                revision: currentWorld.revision + 1,
                updated_at: updatedAt,
                robots,
                events: [
                    ...currentWorld.events,
                    {
                        id: `event-${taskId}-started`,
                        timestamp: updatedAt,
                        type: 'task_started',
                        robot_id: robotId,
                        task_id: taskId,
                        message: `${harvestingRobot.name} started harvesting Wheat.`,
                        data: {},
                    },
                ].slice(-100),
            };
        });
    }

    function sellInventoryItem(robotId, itemId) {
        setWorld((currentWorld) => {
            let seller = null;
            let soldItem = null;
            let earnings = 0;

            const robots = currentWorld.robots.map((robot) => {
                const item = robot.game.inventory[itemId];

                if (
                    robot.id !== robotId
                    || robot.game.location !== 'market'
                    || !robot.physical.online
                    || robot.physical.stopped
                    || robot.task
                    || !item
                    || item.quantity <= 0
                    || !Number.isFinite(item.sell_price)
                ) {
                    return robot;
                }

                seller = robot;
                soldItem = item;
                earnings = item.quantity * item.sell_price;

                const inventory = { ...robot.game.inventory };
                delete inventory[itemId];

                return {
                    ...robot,
                    game: {
                        ...robot.game,
                        money: robot.game.money + earnings,
                        inventory,
                    },
                };
            });

            if (!seller || !soldItem) {
                return currentWorld;
            }

            const updatedAt = new Date().toISOString();
            const currentGold = robots.reduce(
                (total, robot) => total + robot.game.money,
                0,
            );
            const goalCompleted = currentGold >= currentWorld.game.goal.target;
            const saleId = `sale-${currentWorld.revision + 1}`;
            const saleEvents = [
                {
                    id: `event-${saleId}-inventory`,
                    timestamp: updatedAt,
                    type: 'inventory_updated',
                    robot_id: robotId,
                    task_id: null,
                    message: `${seller.name} sold ${soldItem.quantity} ${soldItem.name}.`,
                    data: {
                        item: itemId,
                        quantity: -soldItem.quantity,
                        total_quantity: 0,
                    },
                },
                {
                    id: `event-${saleId}-gold`,
                    timestamp: updatedAt,
                    type: 'gold_updated',
                    robot_id: robotId,
                    task_id: null,
                    message: `${seller.name} earned ${earnings} gold.`,
                    data: {
                        earnings,
                        balance: seller.game.money + earnings,
                    },
                },
            ];

            if (goalCompleted && currentWorld.game.status !== 'COMPLETED') {
                saleEvents.push({
                    id: `event-${saleId}-goal`,
                    timestamp: updatedAt,
                    type: 'game_completed',
                    robot_id: robotId,
                    task_id: null,
                    message: `The crew reached ${currentGold} gold and completed the goal.`,
                    data: {},
                });
            }

            return {
                ...currentWorld,
                revision: currentWorld.revision + 1,
                updated_at: updatedAt,
                game: {
                    ...currentWorld.game,
                    status: goalCompleted ? 'COMPLETED' : currentWorld.game.status,
                    goal: {
                        ...currentWorld.game.goal,
                        current: currentGold,
                    },
                },
                robots,
                events: [
                    ...currentWorld.events,
                    ...saleEvents,
                ].slice(-100),
            };
        });
    }

    function buyMarketItem(itemId) {
        setWorld((currentWorld) => {
            if (currentWorld.game.status === 'COMPLETED') {
                return currentWorld;
            }

            const buyer = getMarketRobot(currentWorld.robots);
            const marketItem = currentWorld.market.items.find(
                (item) => item.id === itemId,
            );

            if (
                !buyer
                || !buyer.physical.online
                || buyer.physical.stopped
                || buyer.task
                || !marketItem
                || !Number.isFinite(marketItem.buy_price)
                || buyer.game.money < marketItem.buy_price
                || marketItem.stock === 0
            ) {
                return currentWorld;
            }

            const existingItem = buyer.game.inventory[itemId];
            const quantity = (existingItem?.quantity ?? 0) + 1;

            const robots = currentWorld.robots.map((robot) => {
                if (robot.id !== buyer.id) {
                    return robot;
                }

                return {
                    ...robot,
                    game: {
                        ...robot.game,
                        money: robot.game.money - marketItem.buy_price,
                        inventory: {
                            ...robot.game.inventory,
                            [itemId]: {
                                name: existingItem?.name ?? marketItem.name,
                                quantity,
                                sell_price: existingItem?.sell_price ?? null,
                            },
                        },
                    },
                };
            });

            const marketItems = currentWorld.market.items.map((item) => {
                if (item.id !== itemId || item.stock === null) {
                    return item;
                }

                return {
                    ...item,
                    stock: item.stock - 1,
                };
            });

            const updatedAt = new Date().toISOString();
            const currentGold = robots.reduce(
                (total, robot) => total + robot.game.money,
                0,
            );
            const purchaseId = `purchase-${currentWorld.revision + 1}`;

            return {
                ...currentWorld,
                revision: currentWorld.revision + 1,
                updated_at: updatedAt,
                game: {
                    ...currentWorld.game,
                    goal: {
                        ...currentWorld.game.goal,
                        current: currentGold,
                    },
                },
                robots,
                market: {
                    ...currentWorld.market,
                    items: marketItems,
                },
                events: [
                    ...currentWorld.events,
                    {
                        id: `event-${purchaseId}-inventory`,
                        timestamp: updatedAt,
                        type: 'inventory_updated',
                        robot_id: buyer.id,
                        task_id: null,
                        message: `${buyer.name} received 1 ${marketItem.name}.`,
                        data: {
                            item: itemId,
                            quantity: 1,
                            total_quantity: quantity,
                        },
                    },
                    {
                        id: `event-${purchaseId}-gold`,
                        timestamp: updatedAt,
                        type: 'gold_updated',
                        robot_id: buyer.id,
                        task_id: null,
                        message: `${buyer.name} spent ${marketItem.buy_price} gold.`,
                        data: {
                            spending: marketItem.buy_price,
                            balance: buyer.game.money - marketItem.buy_price,
                        },
                    },
                ].slice(-100),
            };
        });
    }

    return {
        world,
        buyMarketItem,
        sellInventoryItem,
        startHarvest,
        startRobotTravel,
    };
}
