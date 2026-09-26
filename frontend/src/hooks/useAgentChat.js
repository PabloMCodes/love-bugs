import { useEffect, useRef, useState } from 'react';
import { chatSocketUrl, discussWorld } from '../api/agentChat.js';

export function useAgentChat(world) {
    const [feed, setFeed] = useState({ messages: [], running: false, provider: 'mock' });
    const [connected, setConnected] = useState(false);
    const [enabled, setEnabled] = useState(false);
    const [provider, setProvider] = useState('mock');
    const [error, setError] = useState(null);
    const worldRef = useRef(world);
    worldRef.current = world;

    useEffect(() => {
        let disposed = false;
        let socket;
        let reconnect;
        let attempts = 0;
        function connect() {
            socket = new WebSocket(chatSocketUrl());
            socket.onopen = () => {
                if (disposed) return;
                attempts = 0;
                setConnected(true);
            };
            socket.onmessage = (event) => {
                if (disposed) return;
                try {
                    const snapshot = JSON.parse(event.data);
                    if (Array.isArray(snapshot.messages)) setFeed(snapshot);
                } catch {
                    setError('Unable to read the chat feed');
                }
            };
            socket.onclose = () => {
                if (disposed) return;
                setConnected(false);
                reconnect = window.setTimeout(connect, Math.min(5000, 1000 * 2 ** attempts++));
            };
            socket.onerror = () => socket.close();
        }
        connect();
        return () => {
            disposed = true;
            window.clearTimeout(reconnect);
            socket?.close();
        };
    }, []);

    useEffect(() => {
        if (!enabled) return;
        let disposed = false;
        let timer;
        const controller = new AbortController();
        async function round() {
            try {
                const snapshot = await discussWorld(worldRef.current, provider, controller.signal);
                if (disposed) return;
                setFeed(snapshot);
                setError(snapshot.error);
                if (snapshot.error) {
                    setEnabled(false);
                    return;
                }
                timer = window.setTimeout(round, Math.max(12000, (snapshot.interval_seconds + 1) * 1000));
            } catch (failure) {
                if (disposed) return;
                setError(failure.message || 'Unable to reach the chat server');
                setEnabled(false);
            }
        }
        setError(null);
        round();
        return () => {
            disposed = true;
            controller.abort();
            window.clearTimeout(timer);
        };
    }, [enabled, provider]);

    return { feed, connected, enabled, setEnabled, provider, setProvider, error };
}
