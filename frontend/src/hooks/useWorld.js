// Own the current world snapshot, connection status, session changes, and revision checks across REST and WebSocket updates.
import { useEffect, useRef, useState } from 'react';
import {
    getWorld,
    resetGame,
    startGame,
    stopGame,
    submitTask,
} from '../api/client.js';
import { worldSocketUrl } from '../api/events.js';
import { mockWorldState } from '../data/mockWorldState.js';
import { getTaskDefinition, taskCatalog } from '../data/taskCatalog.js';
import { movePoseToward } from '../simulation/movement.js';
import { getMarketRobot } from '../utils/marketRobots.js';

const simulationStepDistance = 5;
const simulationTickMilliseconds = 250;

function createRequestId() {
    return globalThis.crypto?.randomUUID?.()
        ?? `request-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isWorldSnapshot(value) {
    return Boolean(
        value
        && typeof value.session_id === 'string'
        && Number.isInteger(value.revision)
        && value.game
        && value.map
        && Array.isArray(value.robots)
        && value.market
        && value.farm
        && Array.isArray(value.farm.crops)
        && Array.isArray(value.farm.plots)
        && value.economy
        && Array.isArray(value.economy.unlocks)
        && Array.isArray(value.economy.unlock_proposals)
        && Array.isArray(value.economy.money_requests)
        && Array.isArray(value.economy.transfers),
    );
}

export function useWorld() {
    const [world, setWorld] = useState(mockWorldState);
    const [connection, setConnection] = useState({
        source: 'connecting',
        connected: false,
        error: null,
    });
    const worldRef = useRef(world);
    const backendSelectedRef = useRef(false);
    const backendVersionRef = useRef({ sessionId: null, revision: -1 });
    worldRef.current = world;

    function applyBackendSnapshot(snapshot) {
        if (!isWorldSnapshot(snapshot)) {
            setConnection((current) => ({
                ...current,
                error: 'The backend sent an invalid world snapshot.',
            }));
            return false;
        }

        const previousVersion = backendVersionRef.current;
        const sessionChanged = (
            previousVersion.sessionId !== null
            && previousVersion.sessionId !== snapshot.session_id
        );

        if (
            !sessionChanged
            && previousVersion.sessionId === snapshot.session_id
            && snapshot.revision <= previousVersion.revision
        ) {
            return false;
        }

        backendVersionRef.current = {
            sessionId: snapshot.session_id,
            revision: snapshot.revision,
        };
        backendSelectedRef.current = true;
        setWorld(snapshot);
        setConnection((current) => ({
            source: 'backend',
            connected: current.connected,
            error: null,
        }));
        return true;
    }

    function reportBackendError(error) {
        setConnection((current) => ({
            ...current,
            error: error?.message || 'Unable to reach the backend.',
        }));
    }

    async function runGameCommand(command) {
        if (!backendSelectedRef.current) {
            throw new Error('Connect to the backend to control the game session.');
        }

        try {
            const snapshot = await command();
            applyBackendSnapshot(snapshot);
            setConnection((current) => ({
                ...current,
                error: null,
            }));
            return snapshot;
        } catch (error) {
            reportBackendError(error);
            throw error;
        }
    }

    function startSession() {
        return runGameCommand(startGame);
    }

    function stopSession() {
        return runGameCommand(stopGame);
    }

    function resetSession() {
        return runGameCommand(resetGame);
    }

    useEffect(() => {
        let disposed = false;
        let socket;
        let reconnectTimer;
        let reconnectAttempts = 0;
        const controller = new AbortController();

        getWorld(controller.signal)
            .then((snapshot) => {
                if (!disposed) {
                    applyBackendSnapshot(snapshot);
                }
            })
            .catch((error) => {
                if (disposed || error.name === 'AbortError') {
                    return;
                }

                setConnection((current) => ({
                    source: backendSelectedRef.current ? 'backend' : 'mock',
                    connected: current.connected,
                    error: backendSelectedRef.current
                        ? error.message
                        : 'Backend unavailable. Running the local demo.',
                }));
            });

        function connect() {
            socket = new WebSocket(worldSocketUrl());

            socket.onopen = () => {
                if (disposed) {
                    return;
                }

                reconnectAttempts = 0;
                setConnection((current) => ({
                    ...current,
                    connected: true,
                }));
            };

            socket.onmessage = (event) => {
                if (disposed) {
                    return;
                }

                try {
                    const message = JSON.parse(event.data);

                    if (message.type === 'world_snapshot') {
                        applyBackendSnapshot(message.data);
                    }
                } catch {
                    setConnection((current) => ({
                        ...current,
                        error: 'Unable to read a backend world update.',
                    }));
                }
            };

            socket.onclose = () => {
                if (disposed) {
                    return;
                }

                setConnection((current) => ({
                    source: backendSelectedRef.current ? 'backend' : 'mock',
                    connected: false,
                    error: backendSelectedRef.current
                        ? 'Backend connection lost. Reconnecting…'
                        : current.error,
                }));
                reconnectTimer = window.setTimeout(
                    connect,
                    Math.min(5000, 1000 * (2 ** reconnectAttempts++)),
                );
            };

            socket.onerror = () => {
                if (!disposed) {
                    setConnection((current) => ({
                        ...current,
                        connected: false,
                    }));
                }
            };
        }

        connect();

        return () => {
            disposed = true;
            controller.abort();
            window.clearTimeout(reconnectTimer);

            if (!socket) {
                return;
            }

            socket.onmessage = null;
            socket.onerror = null;
            socket.onclose = null;

            if (socket.readyState === WebSocket.CONNECTING) {
                socket.onopen = () => socket.close();
            } else if (socket.readyState === WebSocket.OPEN) {
                socket.close();
            }
        };
    }, []);

    useEffect(() => {
        const simulationTimer = window.setInterval(() => {
            setWorld((currentWorld) => {
                if (backendSelectedRef.current) {
                    return currentWorld;
                }

                const simulatedRobots = currentWorld.robots.filter(
                    (robot) => (
                        robot.task?.status === 'NAVIGATING'
                        || (
                            robot.task?.status === 'ACTIVE'
                            && getTaskDefinition(robot.task.action)?.type === 'activity'
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

                        const taskDefinition = getTaskDefinition(robot.task.action);
                        const beginsActivity = (
                            movement.arrived
                            && taskDefinition?.type === 'activity'
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

                            if (beginsActivity) {
                                simulationEvents.push({
                                    id: `event-${robot.task.id}-started`,
                                    timestamp: updatedAt,
                                    type: 'task_started',
                                    robot_id: robot.id,
                                    task_id: robot.task.id,
                                    message: `${robot.name} started ${taskDefinition.label.toLowerCase()}.`,
                                    data: {},
                                });
                            }
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
                            task: movement.arrived
                                ? beginsActivity
                                    ? {
                                        ...robot.task,
                                        status: 'ACTIVE',
                                        progress: 0,
                                    }
                                    : null
                                : robot.task,
                        };
                    }

                    const activityTask = getTaskDefinition(robot.task?.action);

                    if (robot.task?.status === 'ACTIVE' && activityTask?.type === 'activity') {
                        const progress = Math.min(
                            1,
                            robot.task.progress + (
                                simulationTickMilliseconds
                                / activityTask.durationMilliseconds
                            ),
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

                        const currentItem = (
                            robot.game.inventory[activityTask.reward.itemId]
                        );
                        const itemQuantity = (
                            currentItem?.quantity ?? 0
                        ) + activityTask.reward.quantity;

                        simulationEvents.push(
                            {
                                id: `event-${robot.task.id}-inventory`,
                                timestamp: updatedAt,
                                type: 'inventory_updated',
                                robot_id: robot.id,
                                task_id: robot.task.id,
                                message: `${robot.name} collected ${activityTask.reward.quantity} ${activityTask.reward.name}.`,
                                data: {
                                    item: activityTask.reward.itemId,
                                    quantity: activityTask.reward.quantity,
                                    total_quantity: itemQuantity,
                                },
                            },
                            {
                                id: `event-${robot.task.id}-completed`,
                                timestamp: updatedAt,
                                type: 'task_completed',
                                robot_id: robot.id,
                                task_id: robot.task.id,
                                message: `${robot.name} completed ${activityTask.label.toLowerCase()}.`,
                                data: {},
                            },
                        );

                        return {
                            ...robot,
                            game: {
                                ...robot.game,
                                inventory: {
                                    ...robot.game.inventory,
                                    [activityTask.reward.itemId]: {
                                        name: currentItem?.name ?? activityTask.reward.name,
                                        quantity: itemQuantity,
                                        sell_price: currentItem?.sell_price ?? activityTask.reward.sellPrice,
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

    async function startRobotTravel(
        robotId,
        destinationId,
        action = taskCatalog.MOVE_TO.action,
    ) {
        const taskReason = action === taskCatalog.RETURN_HOME.action
            ? 'Return to homebase.'
            : `Travel to ${destinationId}.`;

        if (backendSelectedRef.current) {
            try {
                let currentWorld = worldRef.current;

                if (currentWorld.game.status !== 'RUNNING') {
                    currentWorld = await startGame();
                    applyBackendSnapshot(currentWorld);
                }

                await submitTask({
                    request_id: createRequestId(),
                    robot_id: robotId,
                    action,
                    location: destinationId,
                    parameters: {},
                    reason: taskReason,
                });
                setConnection((current) => ({
                    ...current,
                    error: null,
                }));
            } catch (error) {
                reportBackendError(error);
            }

            return;
        }

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
                        action,
                        location: destinationId,
                        status: 'NAVIGATING',
                        progress: 0,
                        parameters: {},
                        reason: taskReason,
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
                        message: action === taskCatalog.RETURN_HOME.action
                            ? 'Robot assigned to return home.'
                            : `Robot assigned to travel to ${destinationId}.`,
                        data: {},
                    },
                ].slice(-100),
            };
        });
    }

    async function startActivity(robotId, action, parameters = {}) {
        const taskDefinition = getTaskDefinition(action);

        if (taskDefinition?.type !== 'activity') {
            return;
        }

        if (backendSelectedRef.current) {
            try {
                let currentWorld = worldRef.current;

                if (currentWorld.game.status !== 'RUNNING') {
                    currentWorld = await startGame();
                    applyBackendSnapshot(currentWorld);
                }

                await submitTask({
                    request_id: createRequestId(),
                    robot_id: robotId,
                    action: taskDefinition.action,
                    location: taskDefinition.requiredLocation,
                    parameters,
                    reason: `${taskDefinition.label} to earn resources.`,
                });
                setConnection((current) => ({
                    ...current,
                    error: null,
                }));
            } catch (error) {
                reportBackendError(error);
            }

            return;
        }

        setWorld((currentWorld) => {
            const updatedAt = new Date().toISOString();
            const taskId = `task-${currentWorld.revision + 1}`;
            let assignedRobot = null;
            let beginsWithTravel = false;

            const robots = currentWorld.robots.map((robot) => {
                const needsTravel = (
                    robot.game.location !== taskDefinition.requiredLocation
                );

                if (
                    robot.id !== robotId
                    || !robot.physical.online
                    || robot.physical.stopped
                    || robot.task
                    || (
                        needsTravel
                        && (
                            !robot.physical.pose
                            || !currentWorld.map.locations[taskDefinition.requiredLocation]
                        )
                    )
                ) {
                    return robot;
                }

                assignedRobot = robot;
                beginsWithTravel = needsTravel;

                return {
                    ...robot,
                    game: {
                        ...robot.game,
                        location: needsTravel ? null : robot.game.location,
                    },
                    task: {
                        id: taskId,
                        robot_id: robot.id,
                        action: taskDefinition.action,
                        location: taskDefinition.requiredLocation,
                        status: needsTravel ? 'NAVIGATING' : 'ACTIVE',
                        progress: 0,
                        parameters,
                        reason: `${taskDefinition.label} to earn resources.`,
                        error: null,
                    },
                };
            });

            if (!assignedRobot) {
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
                        id: `event-${taskId}-${beginsWithTravel ? 'assigned' : 'started'}`,
                        timestamp: updatedAt,
                        type: beginsWithTravel ? 'task_assigned' : 'task_started',
                        robot_id: robotId,
                        task_id: taskId,
                        message: beginsWithTravel
                            ? `${assignedRobot.name} is traveling to ${taskDefinition.requiredLocation} to ${taskDefinition.label.toLowerCase()}.`
                            : `${assignedRobot.name} started ${taskDefinition.label.toLowerCase()}.`,
                        data: {},
                    },
                ].slice(-100),
            };
        });
    }

    async function sellInventoryItem(robotId, itemId, requestedQuantity = null) {
        if (backendSelectedRef.current) {
            try {
                let currentWorld = worldRef.current;
                const robot = currentWorld.robots.find(
                    (candidate) => candidate.id === robotId,
                );
                const availableQuantity = robot?.game.inventory[itemId]?.quantity;
                const quantity = requestedQuantity ?? availableQuantity;

                if (
                    !Number.isInteger(quantity)
                    || quantity <= 0
                    || quantity > availableQuantity
                ) {
                    throw new Error('That inventory item is no longer available.');
                }

                if (currentWorld.game.status !== 'RUNNING') {
                    currentWorld = await startGame();
                    applyBackendSnapshot(currentWorld);
                }

                await submitTask({
                    request_id: createRequestId(),
                    robot_id: robotId,
                    action: taskCatalog.SELL.action,
                    location: taskCatalog.SELL.requiredLocation,
                    parameters: { item: itemId, quantity },
                    reason: `Sell ${quantity} ${itemId} at the market.`,
                });
                setConnection((current) => ({
                    ...current,
                    error: null,
                }));
            } catch (error) {
                reportBackendError(error);
            }

            return;
        }

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
            const goalCompleted = (
                currentGold >= currentWorld.game.goal.target
                && currentWorld.game.stage >= 3
            );
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

    async function buyMarketItem(itemId, robotId = null, requestedQuantity = 1) {
        if (backendSelectedRef.current) {
            try {
                let currentWorld = worldRef.current;
                const buyer = robotId
                    ? currentWorld.robots.find((robot) => robot.id === robotId)
                    : getMarketRobot(currentWorld.robots);

                if (!buyer) {
                    throw new Error('No robot is available to receive this item.');
                }
                if (!Number.isInteger(requestedQuantity) || requestedQuantity <= 0) {
                    throw new Error('Purchase quantity must be a positive integer.');
                }

                if (currentWorld.game.status !== 'RUNNING') {
                    currentWorld = await startGame();
                    applyBackendSnapshot(currentWorld);
                }

                await submitTask({
                    request_id: createRequestId(),
                    robot_id: buyer.id,
                    action: taskCatalog.BUY.action,
                    location: taskCatalog.BUY.requiredLocation,
                    parameters: {
                        item: itemId,
                        quantity: requestedQuantity,
                    },
                    reason: `Buy ${requestedQuantity} ${itemId} at the market.`,
                });
                setConnection((current) => ({
                    ...current,
                    error: null,
                }));
            } catch (error) {
                reportBackendError(error);
            }

            return;
        }

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
                || (currentWorld.game.stage ?? 1) < (marketItem.required_stage ?? 1)
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

    function dispatchAgentTask(proposal) {
        const taskDefinition = getTaskDefinition(proposal.action);

        if (!taskDefinition || proposal.status !== 'proposed') {
            return;
        }

        if (taskDefinition.type === 'activity') {
            startActivity(
                proposal.robot_id,
                proposal.action,
                proposal.parameters ?? {},
            );
            return;
        }

        if (proposal.action === taskCatalog.MOVE_TO.action && proposal.location) {
            startRobotTravel(proposal.robot_id, proposal.location);
            return;
        }

        if (proposal.action === taskCatalog.RETURN_HOME.action) {
            startRobotTravel(
                proposal.robot_id,
                taskDefinition.requiredLocation,
                taskDefinition.action,
            );
            return;
        }

        if (
            proposal.action === taskCatalog.BUY.action
            && proposal.parameters?.item
        ) {
            buyMarketItem(
                proposal.parameters.item,
                proposal.robot_id,
                proposal.parameters.quantity,
            );
            return;
        }

        if (
            proposal.action === taskCatalog.SELL.action
            && proposal.parameters?.item
        ) {
            sellInventoryItem(
                proposal.robot_id,
                proposal.parameters.item,
                proposal.parameters.quantity,
            );
        }
    }

    return {
        world,
        connection,
        buyMarketItem,
        dispatchAgentTask,
        resetSession,
        sellInventoryItem,
        startSession,
        stopSession,
    };
}
