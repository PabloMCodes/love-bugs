"""Publish complete world snapshots when the authoritative revision changes."""

import asyncio
from contextlib import suppress
import math

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.state import WorldStore


def create_events_router(store: WorldStore, *, interval_seconds: float = .1) -> APIRouter:
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise ValueError('interval_seconds must be a positive finite number')

    router = APIRouter(tags=['world'])

    @router.websocket('/events')
    async def events(socket: WebSocket):
        await socket.accept()
        last_session_id = None
        last_revision = -1

        async def wait_for_disconnect():
            try:
                while True:
                    message = await socket.receive()
                    if message['type'] == 'websocket.disconnect':
                        return
            except (WebSocketDisconnect, OSError, RuntimeError):
                return

        disconnect_task = asyncio.create_task(wait_for_disconnect())

        try:
            while not disconnect_task.done():
                snapshot = store.snapshot()
                if (
                    snapshot.session_id != last_session_id
                    or snapshot.revision > last_revision
                ):
                    await socket.send_json({
                        'type': 'world_snapshot',
                        'data': snapshot.model_dump(mode='json'),
                    })
                    last_session_id = snapshot.session_id
                    last_revision = snapshot.revision

                await asyncio.sleep(interval_seconds)
        except (WebSocketDisconnect, OSError, RuntimeError):
            return
        finally:
            disconnect_task.cancel()
            with suppress(asyncio.CancelledError):
                await disconnect_task

    return router
