"""Host autonomous planning against the authoritative world and task service."""

import asyncio
import logging
import math

from app.agents.orchestrator import AgentOrchestrator
from app.schemas import (
    EconomyResponseRequest,
    MoneyRequestCreate,
    MoneyTransferRequest,
    StageUnlockProposalRequest,
    TaskRequest,
)
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
        self.poll_interval_seconds = interval

    def read_world(self) -> dict:
        return self.store.snapshot().model_dump(mode='json')

    async def submit_task(self, session_id: str, request: dict) -> bool:
        try:
            action = request.get('action')
            parameters = request.get('parameters', {})
            if action in {
                'PROPOSE_UNLOCK',
                'RESPOND_UNLOCK',
                'TRANSFER_MONEY',
                'REQUEST_MONEY',
                'RESPOND_MONEY',
            }:
                common = {
                    'request_id': request.get('request_id'),
                }
                resource_id = None
                if action == 'PROPOSE_UNLOCK':
                    command = StageUnlockProposalRequest(
                        **common,
                        proposer_id=request.get('robot_id'),
                        stage=parameters.get('stage'),
                        contributions=parameters.get('contributions'),
                    )
                elif action == 'RESPOND_UNLOCK':
                    command = EconomyResponseRequest(
                        **common,
                        robot_id=request.get('robot_id'),
                        accepted=parameters.get('accepted'),
                    )
                    resource_id = parameters.get('proposal_id')
                elif action == 'TRANSFER_MONEY':
                    command = MoneyTransferRequest(
                        **common,
                        sender_id=request.get('robot_id'),
                        recipient_id=parameters.get('recipient_id'),
                        amount=parameters.get('amount'),
                        purpose=request.get('reason'),
                    )
                elif action == 'REQUEST_MONEY':
                    command = MoneyRequestCreate(
                        **common,
                        requester_id=request.get('robot_id'),
                        recipient_id=parameters.get('recipient_id'),
                        amount=parameters.get('amount'),
                        purpose=request.get('reason'),
                    )
                else:
                    command = EconomyResponseRequest(
                        **common,
                        robot_id=request.get('robot_id'),
                        accepted=parameters.get('accepted'),
                    )
                    resource_id = parameters.get('money_request_id')
                await asyncio.to_thread(
                    self.store.apply_economy_for_session,
                    session_id,
                    action,
                    command,
                    resource_id=resource_id,
                )
            else:
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
        return await self.orchestrator.tick(self.read_world, self.submit_task)

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
