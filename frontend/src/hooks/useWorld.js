// Own the current world snapshot, connection status, session changes, and revision checks across REST and WebSocket updates.
import { useEffect, useState } from 'react';
import { mockWorldState } from '../data/mockWorldState.js';
import { movePoseToward } from '../simulation/movement.js';

const simulationStepDistance = 5;
const simulationTickMilliseconds = 250;

export function useWorld() {
    const [world, setWorld] = useState(mockWorldState);

    useEffect(() => {
        const simulationTimer = window.setInterval(() => {
            setWorld((currentWorld) => {
                const navigatingRobots = currentWorld.robots.filter(
                    (robot) => robot.task?.status === 'NAVIGATING',
                );

                if (navigatingRobots.length === 0) {
                    return currentWorld;
                }

                const updatedAt = new Date().toISOString();
                const arrivalEvents = [];

                const robots = currentWorld.robots.map((robot) => {
                    if (robot.task?.status !== 'NAVIGATING' || !robot.physical.pose) {
                        return robot;
                    }

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
                        arrivalEvents.push({
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
                });

                return {
                    ...currentWorld,
                    revision: currentWorld.revision + 1,
                    updated_at: updatedAt,
                    robots,
                    events: [
                        ...currentWorld.events,
                        ...arrivalEvents,
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

    return { world, startRobotTravel };
}
