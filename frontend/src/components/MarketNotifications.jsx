import { useEffect, useRef, useState } from 'react';

const visibleDurationMs = 5000;

function marketNotification(event, events, robots, marketItems) {
    const isSale = Number.isFinite(event.data?.earnings);
    const eventIndex = events.findIndex((candidate) => candidate.id === event.id);
    const precedingEvents = eventIndex >= 0 ? events.slice(0, eventIndex) : events;
    const inventoryEvent = [...precedingEvents].reverse().find((candidate) => (
        candidate.task_id === event.task_id
        && candidate.robot_id === event.robot_id
        && candidate.type === 'inventory_updated'
        && (isSale ? candidate.data?.quantity < 0 : candidate.data?.quantity > 0)
    ));
    const robot = robots.find((candidate) => candidate.id === event.robot_id);
    const itemId = inventoryEvent?.data?.item;
    const itemName = marketItems.find((item) => item.id === itemId)?.name
        ?? itemId?.replaceAll('_', ' ')
        ?? 'an item';
    const quantity = Math.abs(inventoryEvent?.data?.quantity ?? 1);
    const saleText = inventoryEvent?.message?.replace(/\.$/, '');

    return {
        id: event.id,
        kind: isSale ? 'sale' : 'purchase',
        label: isSale ? 'Market sale' : 'Market purchase',
        message: isSale && saleText
            ? saleText
            : `${robot?.name ?? 'A robot'} ${isSale ? 'sold' : 'bought'} ${quantity} ${itemName}`,
        gold: isSale ? event.data.earnings : event.data.spending,
    };
}

export default function MarketNotifications({ world }) {
    const [notifications, setNotifications] = useState([]);
    const session = useRef(null);
    const seen = useRef(new Set());
    const timers = useRef(new Map());

    useEffect(() => () => {
        timers.current.forEach((timer) => window.clearTimeout(timer));
    }, []);

    useEffect(() => {
        const transactionEvents = world.events.filter((event) => (
            event.type === 'gold_updated'
            && (
                Number.isFinite(event.data?.earnings)
                || Number.isFinite(event.data?.spending)
            )
        ));

        if (session.current !== world.session_id) {
            timers.current.forEach((timer) => window.clearTimeout(timer));
            timers.current.clear();
            session.current = world.session_id;
            seen.current = new Set(transactionEvents.map((event) => event.id));
            setNotifications([]);
            return;
        }

        const newTransactions = transactionEvents.filter((event) => !seen.current.has(event.id));
        if (newTransactions.length === 0) return;

        const additions = newTransactions.map((event) => {
            seen.current.add(event.id);
            return marketNotification(
                event,
                world.events,
                world.robots,
                world.market.items,
            );
        });
        setNotifications((current) => [...current, ...additions].slice(-4));

        additions.forEach((notification) => {
            const timer = window.setTimeout(() => {
                setNotifications((current) => (
                    current.filter((item) => item.id !== notification.id)
                ));
                timers.current.delete(notification.id);
            }, visibleDurationMs);
            timers.current.set(notification.id, timer);
        });
    }, [world.events, world.market.items, world.robots, world.session_id]);

    return (
        <aside
            className="pointer-events-none fixed inset-y-0 right-0 z-50 flex w-full max-w-[19rem] flex-col items-end gap-2 overflow-hidden px-3 pt-20"
            aria-label="Market notifications"
            aria-live="polite"
        >
            {notifications.map((notification) => (
                <div
                    key={notification.id}
                    className="market-notification-paper market-parchment-card w-full max-w-[16rem] p-3.5 text-[#422313]"
                    role="status"
                >
                    <p className="text-xs font-bold uppercase tracking-wide text-[#805431]">
                        {notification.label}
                    </p>
                    <p className={`market-notification-copy mt-0.5 text-sm font-bold ${
                        notification.kind === 'sale'
                            ? 'market-notification-sale'
                            : 'market-notification-purchase'
                    }`}>
                        {notification.message} for {notification.gold} gold.
                    </p>
                </div>
            ))}
        </aside>
    );
}
