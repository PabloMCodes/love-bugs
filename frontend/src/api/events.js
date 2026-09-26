// Build the authoritative world event URL from the same configurable backend base URL as REST.
const apiBase = (
    import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
).replace(/\/$/, '');

export function worldSocketUrl() {
    const url = new URL(`${apiBase}/events`, window.location.href);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return url.toString();
}
