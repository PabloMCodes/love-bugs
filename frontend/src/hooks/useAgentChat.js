import { useEffect, useState } from 'react';
import { chatSocketUrl } from '../api/agentChat.js';

export function useAgentChat() {
    const [feed, setFeed] = useState({
        messages: [],
        running: false,
        provider: 'mock',
        mode: 'discussion',
    });
    const [connected, setConnected] = useState(false);
    const [error, setError] = useState(null);

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
                    if (Array.isArray(snapshot.messages)) {
                        setFeed(snapshot);
                        setError(null);
                    }
                } catch {
                    setError('Unable to read the chat feed');
                }
            };
            socket.onclose = () => {
                if (disposed) return;
                setConnected(false);
                reconnect = window.setTimeout(connect, Math.min(5000, 1000 * 2 ** attempts++));
            };
            socket.onerror = () => {
                if (disposed) return;
                setConnected(false);
            };
        }
        connect();
        return () => {
            disposed = true;
            window.clearTimeout(reconnect);

            if (!socket) return;

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

    return { feed, connected, error };
}
