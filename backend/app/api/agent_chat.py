"""Spectator chat transport; discussions propose tasks without executing them."""

import asyncio
from copy import deepcopy
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.agents.chat import AgentChat
from app.agents.orchestrator import api_error_summary
from app.agents.planner import MockPlanner, available, validate_decision
from app.config import AgentConfig
from google.genai.errors import APIError


class DiscussionRequest(BaseModel):
    provider: Literal['mock', 'gemini'] = 'mock'
    world: dict


def validate_world(world):
    """Validate fields needed by planners before consuming any model quota."""
    try:
        if not isinstance(world['session_id'], str) or not world['session_id']:
            raise ValueError('Missing session ID')
        if len(world['session_id']) > 100:
            raise ValueError('Session ID too long')
        robots = world['robots']
        if not isinstance(robots, list) or not 1 <= len(robots) <= 10:
            raise ValueError('Expected 1–10 robots')
        ids = [r['id'] for r in robots]
        if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError('Robot IDs must be unique nonempty strings')
        if world['game']['status'] not in ('READY', 'RUNNING', 'STOPPED', 'COMPLETED'):
            raise ValueError('Invalid game status')
        if not isinstance(world['map']['locations'], dict) or not isinstance(world['market']['items'], list):
            raise ValueError('Missing map or market')
        for robot in robots:
            available(world, robot, discussion=True)
            if not isinstance(robot['game']['inventory'], dict):
                raise ValueError('Invalid inventory')
            float(robot['game']['money'])
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(422, 'Invalid world snapshot for agent discussion') from error


def discussion_world(world):
    """Adapt the frontend's buy-only catalog for read-only discussion.

    Inventory sale prices belong to the frontend simulation, not authoritative
    backend transactions. Never use this adapter to authorize real trades.
    """
    snapshot = deepcopy(world)
    catalog = {item['id']: item for item in snapshot['market']['items']}
    for item in catalog.values():
        item.setdefault('sell_price', None)
        item.setdefault('buy_price', None)
        item.setdefault('stock', None)
    for robot in snapshot['robots']:
        for item_id, item in robot['game']['inventory'].items():
            if item_id not in catalog and isinstance(item, dict):
                catalog[item_id] = {
                    'id': item_id, 'name': item.get('name', item_id),
                    'buy_price': None, 'sell_price': item.get('sell_price'), 'stock': None,
                }
    snapshot['market']['items'] = list(catalog.values())
    return snapshot


class DiscussionService:
    def __init__(self, config=None):
        self.config = config or AgentConfig.from_env()
        self.chat = AgentChat()
        self.lock = asyncio.Lock()
        self.planners = {'mock': MockPlanner()}
        self.next_round = 0
        self.provider = 'mock'
        self.running = False
        self.error = None

    def snapshot(self):
        return {**self.chat.snapshot(), 'provider': self.provider,
                'running': self.running, 'error': self.error, 'mode': 'discussion',
                'interval_seconds': self.config.interval_seconds}

    async def discuss(self, request):
        validate_world(request.world)
        if self.lock.locked():
            raise HTTPException(409, 'A discussion round is already running')
        if time.monotonic() < self.next_round:
            raise HTTPException(429, 'Wait before starting another discussion round')
        async with self.lock:
            world = discussion_world(request.world)
            if request.provider not in self.planners:
                from app.agents.gemini import GeminiPlanner
                try:
                    self.planners[request.provider] = GeminiPlanner(self.config.model)
                except ValueError as error:
                    raise HTTPException(503, str(error)) from error
            if self.provider != request.provider:
                self.chat = AgentChat()
            self.provider = request.provider
            self.chat.reset(world['session_id'])
            self.running = True
            self.error = None
            self.next_round = time.monotonic() + self.config.interval_seconds
            try:
                for robot in world['robots']:
                    if not available(world, robot, discussion=True):
                        continue
                    decision = await asyncio.wait_for(
                        self.planners[request.provider].decide(self.chat.context(world), robot['id']),
                        self.config.timeout_seconds,
                    )
                    validate_decision(world, robot['id'], decision, discussion=True)
                    self.chat.publish(world, robot['id'], decision, status='proposed')
            except APIError as error:
                self.error = api_error_summary(error)
            except (TimeoutError, ValidationError, ValueError):
                self.error = 'The agent could not produce a valid message. Please retry.'
            except Exception:
                self.error = 'Agent discussion failed. Please retry.'
            finally:
                self.running = False
                self.next_round = time.monotonic() + self.config.interval_seconds
            return self.snapshot()


def create_router(service):
    router = APIRouter(prefix='/agent-chat', tags=['agent-chat'])

    @router.post('/round')
    async def discuss(request: DiscussionRequest):
        return await service.discuss(request)

    @router.get('')
    async def history():
        return service.snapshot()

    @router.websocket('/events')
    async def events(socket: WebSocket):
        await socket.accept()
        try:
            # Full bounded snapshots also act as heartbeats and replay on reconnect.
            while True:
                await socket.send_json(service.snapshot())
                await asyncio.sleep(.5)
        except (WebSocketDisconnect, OSError, RuntimeError):
            return

    return router
