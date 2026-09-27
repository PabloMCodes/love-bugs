"""Schedule per-robot planning through a host's authoritative task service."""

import asyncio
from copy import deepcopy
from dataclasses import asdict, dataclass
import logging
import math
import os
import re
from urllib.parse import quote
import time
from typing import Awaitable, Callable
from uuid import uuid4

from google.genai.errors import APIError
from pydantic import ValidationError

from app.agents.chat import AgentChat
from app.agents.planner import Planner, available, validate_decision

logger = logging.getLogger(__name__)


def api_error_summary(error: APIError) -> str:
    """Include service diagnostics without response headers or API credentials."""
    message = f'Gemini API {error.code} {error.status or "ERROR"}: {error.message or "Request failed"}'
    for name in ('GOOGLE_API_KEY', 'GEMINI_API_KEY'):
        secret = os.environ.get(name)
        if secret:
            message = message.replace(secret, '[REDACTED]').replace(quote(secret, safe=''), '[REDACTED]')
    message = re.sub(r'(?i)([?&](?:key|api_key)=)[^&\s]+', r'\1[REDACTED]', message)
    message = re.sub(r'AIza[A-Za-z0-9_-]+', '[REDACTED]', message)
    return ' '.join(message.split())[:1500]


@dataclass
class Outcome:
    robot_id: str
    status: str
    reason: str
    request: dict | None = None

    def to_dict(self):
        return asdict(self)


class AgentOrchestrator:
    def __init__(self, planner: Planner, *, interval: float = 10, timeout: float = 20, chat: AgentChat | None = None):
        if any(not math.isfinite(value) or value <= 0 for value in (interval, timeout)):
            raise ValueError('Agent interval and timeout must be positive')
        self.chat = chat if chat is not None else AgentChat()
        self.planner = planner
        self.interval = interval
        self.timeout = timeout
        self._next_attempt: dict[tuple[str, str], float] = {}
        self._lock = asyncio.Lock()
        self._session_id = None

    async def tick(self, read_world: Callable[[], dict],
                   submit_task: Callable[[str, dict], Awaitable[bool]]) -> list[Outcome]:
        """Plan for idle robots; host submission must atomically revalidate and assign.

        read_world returns the latest snapshot. submit_task(session_id, request)
        returns True only after acceptance is visible in read_world. It must use
        request_id for idempotency and reject outdated sessions. No automatic
        retry is made on ambiguous submission errors. A new tick is host-driven.
        """
        if self._lock.locked():
            return []
        async with self._lock:
            initial = deepcopy(read_world())
            session_id = initial['session_id']
            if session_id != self._session_id:
                self._next_attempt.clear()
                self._session_id = session_id
                self.chat.reset(session_id)
            outcomes = []
            # Independent agents run sequentially so each sees accepted teammate tasks.
            for robot in initial['robots']:
                robot_id = robot['id']
                world = deepcopy(read_world())
                if world['session_id'] != session_id:
                    break
                current = next((r for r in world['robots'] if r['id'] == robot_id), None)
                key = (session_id, robot_id)
                if current is None or not available(world, current):
                    continue
                if time.monotonic() < self._next_attempt.get(key, 0):
                    continue
                self._next_attempt[key] = time.monotonic() + self.interval
                try:
                    decision = await asyncio.wait_for(self.planner.decide(self.chat.context(world), robot_id), self.timeout)
                    latest = deepcopy(read_world())
                    if latest['session_id'] != session_id:
                        outcomes.append(Outcome(robot_id, 'rejected', 'Game session changed'))
                        break
                    validate_decision(latest, robot_id, decision)
                except Exception as error:
                    logger.warning('Robot %s planning rejected (%s)', robot_id, type(error).__name__)
                    if isinstance(error, ValidationError):
                        # Log field locations/types, never input values or credentials.
                        for detail in error.errors(include_input=False, include_context=False):
                            logger.warning('Validation field %s: %s',
                                           '.'.join(map(str, detail['loc'])) or '<decision>',
                                           detail['type'])
                    reason = 'Planning failed or decision no longer valid'
                    if isinstance(error, APIError):
                        reason = api_error_summary(error)
                        logger.warning('%s', reason)
                    outcomes.append(Outcome(robot_id, 'error', reason))
                    continue
                if decision.action == 'WAIT':
                    self.chat.publish(latest, robot_id, decision, status='waiting')
                    outcomes.append(Outcome(robot_id, 'waiting', decision.reason))
                    continue
                if decision.action in ('BUY', 'SELL'):
                    parameters = {
                        'item': decision.item,
                        'quantity': decision.quantity,
                    }
                elif decision.action == 'HARVEST':
                    parameters = {'plot_id': decision.plot_id}
                else:
                    parameters = {}
                request = {'request_id': uuid4().hex, 'robot_id': robot_id,
                           'action': decision.action, 'location': decision.location,
                           'parameters': parameters, 'reason': decision.reason}
                try:
                    accepted = await asyncio.wait_for(submit_task(session_id, request), self.timeout)
                except asyncio.CancelledError:
                    self._next_attempt[key] = float('inf')
                    raise
                except Exception as error:
                    # Block this robot until session reset or host reconciliation. A
                    # timeout may mean the service accepted the task but lost its reply.
                    self._next_attempt[key] = float('inf')
                    logger.error('Robot %s submission uncertain (%s)', robot_id, type(error).__name__)
                    outcomes.append(Outcome(robot_id, 'uncertain', 'Reconcile task before resuming', request))
                    continue
                if accepted:
                    self.chat.publish(latest, robot_id, decision, status='accepted')
                outcomes.append(Outcome(robot_id, 'accepted' if accepted else 'rejected',
                                        decision.reason, request))
            return outcomes

    def reconcile(self, session_id: str, robot_id: str) -> None:
        """Host calls only after resolving an uncertain submission against task state."""
        self._next_attempt[(session_id, robot_id)] = time.monotonic() + self.interval
