"""Expire hardware telemetry without coupling adapters to game rules."""

import asyncio
from datetime import datetime, timezone
import logging
import math

from app.state import WorldStateError, WorldStore


class TelemetryWatchdog:
    def __init__(
        self,
        store: WorldStore,
        *,
        health_timeout_seconds: float,
        pose_timeout_seconds: float,
        interval_seconds: float,
    ):
        values = (
            health_timeout_seconds,
            pose_timeout_seconds,
            interval_seconds,
        )
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError('Telemetry watchdog intervals must be positive and finite')
        self.store = store
        self.health_timeout_seconds = health_timeout_seconds
        self.pose_timeout_seconds = pose_timeout_seconds
        self.interval_seconds = interval_seconds

    def tick(self, checked_at: datetime | None = None) -> None:
        self.store.expire_stale_telemetry(
            checked_at or datetime.now(timezone.utc),
            health_timeout_seconds=self.health_timeout_seconds,
            pose_timeout_seconds=self.pose_timeout_seconds,
        )

    async def run(self) -> None:
        try:
            while True:
                try:
                    await asyncio.to_thread(self.tick)
                except WorldStateError as error:
                    if error.code != 'PERSISTENCE_UNAVAILABLE':
                        raise
                    logging.getLogger(__name__).warning(
                        'History unavailable; telemetry expiration will retry',
                    )
                await asyncio.sleep(self.interval_seconds)
        except asyncio.CancelledError:
            return
