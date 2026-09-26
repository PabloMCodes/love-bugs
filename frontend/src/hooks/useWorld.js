// Own the current world snapshot, connection status, session changes, and revision checks across REST and WebSocket updates.
import { useEffect, useState } from 'react';
import { mockWorldState } from '../data/mockWorldState.js';
import { movePoseToward } from '../simulation/movement.js';

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

    return { world, startHarvest, startRobotTravel };
}
