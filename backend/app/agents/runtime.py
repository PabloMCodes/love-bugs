"""Host autonomous planning against the authoritative world and task service."""

import asyncio
import logging
import math

from app.agents.orchestrator import AgentOrchestrator
from app.agents.banter import BanterCoordinator
from app.schemas import TaskRequest
from app.state import WorldStateError, WorldStore


logger = logging.getLogger(__name__)


class AutonomyRunner:
    def __init__(
        self,
        store: WorldStore,
        orchestrator: AgentOrchestrator,
        *,
        poll_interval_seconds: float | None = None,
    ):
        interval = (
            min(1.0, orchestrator.interval)
            if poll_interval_seconds is None
            else poll_interval_seconds
        )
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError('Autonomy poll interval must be positive and finite')
        self.store = store
        self.orchestrator = orchestrator
        self.banter = BanterCoordinator(orchestrator.planner, orchestrator.chat)
        self.poll_interval_seconds = interval

    def read_world(self) -> dict:
        return self.store.snapshot().model_dump(mode='json')

    async def submit_task(self, session_id: str, request: dict) -> bool:
        try:
            task_request = TaskRequest.model_validate(request)
            await asyncio.to_thread(
                self.store.assign_task_for_session,
                session_id,
                task_request,
            )
            return True
        except WorldStateError as error:
            logger.info(
                'Autonomous task rejected for %s (%s)',
                request.get('robot_id', 'unknown'),
                error.code,
            )
            return False

    async def tick(self):
        outcomes = await self.orchestrator.tick(self.read_world, self.submit_task)
        await self.banter.tick(self.read_world(), task_activity=any(
            outcome.status != 'waiting' for outcome in outcomes))
        return outcomes

    async def run(self) -> None:
        try:
            while True:
                try:
                    await self.tick()
                except Exception:
                    logger.exception('Autonomous planning tick failed')
                await asyncio.sleep(self.poll_interval_seconds)
        except asyncio.CancelledError:
            return
        finally:
            await self.banter.close()
