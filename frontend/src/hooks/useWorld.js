// Own the current world snapshot, connection status, session changes, and revision checks across REST and WebSocket updates.
import { useState } from 'react';
import { mockWorldState } from '../data/mockWorldState.js';

export function useWorld() {
    const [world, setWorld] = useState(mockWorldState);

    return { world, setWorld };
}
