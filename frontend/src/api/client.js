// Send HTTP requests using a configurable backend URL and handle the error envelope defined in api.md.
const apiBase = (
    import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
).replace(/\/$/, '');

async function request(path, options = {}) {
    const response = await fetch(`${apiBase}${path}`, options);
    const text = await response.text();
    let result = null;

    if (text) {
        try {
            result = JSON.parse(text);
        } catch {
            throw new Error('The backend returned an unreadable response.');
        }
    }

    if (!response.ok) {
        throw new Error(
            result?.error?.message
            || result?.detail
            || `Backend request failed with status ${response.status}.`,
        );
    }

    return result;
}

export function getWorld(signal) {
    return request('/world', { signal });
}

export function startGame(signal) {
    return request('/game/start', {
        method: 'POST',
        signal,
    });
}

export function stopGame(signal) {
    return request('/game/stop', {
        method: 'POST',
        signal,
    });
}

export function resetGame(signal) {
    return request('/game/reset', {
        method: 'POST',
        signal,
    });
}

export function submitTask(task, signal) {
    return request('/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(task),
        signal,
    });
}
