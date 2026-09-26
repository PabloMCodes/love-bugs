const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

export function chatSocketUrl() {
    const url = new URL(`${apiBase}/agent-chat/events`, window.location.href);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return url.toString();
}

export async function discussWorld(world, provider, signal) {
    const response = await fetch(`${apiBase}/agent-chat/round`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ world, provider }),
        signal,
    });
    const result = await response.json();
    if (!response.ok) {
        throw new Error(typeof result.detail === 'string' ? result.detail : 'Unable to start discussion');
    }
    return result;
}
