"""Compose the live game, history recorder, simulator and spectator chat."""

import asyncio
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent_chat import DiscussionService, create_router
from app.agents.chat import AgentChat
from app.agents.orchestrator import AgentOrchestrator
from app.agents.planner import MockPlanner
from app.agents.runtime import AutonomyRunner
from app.api.errors import install_error_handlers
from app.api.events import create_events_router
from app.api.routes import create_world_router
from app.simulation.simulator import SimulationRunner
from app.state import WorldStore, default_world
from app.config import AgentConfig, Settings
from app.persistence.store import Store
from app.persistence.recorder import WorldRecorder
from app.robots.watchdog import TelemetryWatchdog
from app.api.history import create_history_router
from uuid import uuid4


def create_app(
    service=None,
    world_store=None,
    run_simulator=None,
    *,
    settings=None,
    agent_config=None,
):
    config = settings or Settings()
    agents = agent_config or AgentConfig.from_env()
    # Explicitly injected stores stay in-memory unless persistence is requested.
    persistent = world_store is None or settings is not None
    history = Store(config) if persistent else None
    if world_store is None:
        initial = default_world(config.game_mode)
        initial['session_id'] = str(uuid4())
        store = WorldStore(initial)
    else:
        store = world_store
    game_loop_enabled = world_store is None if run_simulator is None else run_simulator
    simulator_enabled = (
        game_loop_enabled
        and store.snapshot().mode == 'simulation'
    )
    simulator = SimulationRunner(store)
    telemetry_watchdog_enabled = (
        game_loop_enabled
        and store.snapshot().mode == 'hardware'
    )
    telemetry_watchdog = TelemetryWatchdog(
        store,
        health_timeout_seconds=config.health_timeout_seconds,
        pose_timeout_seconds=config.pose_timeout_seconds,
        interval_seconds=config.telemetry_check_interval_seconds,
    )
    autonomy_enabled = game_loop_enabled and config.autonomy_enabled
    shared_chat = AgentChat()
    conversation = service or DiscussionService(
        agents,
        chat=shared_chat,
        autonomous=autonomy_enabled,
        provider=config.autonomy_provider if autonomy_enabled else 'mock',
    )
    orchestrator = None
    autonomy_runner = None
    if autonomy_enabled:
        if config.autonomy_provider == 'gemini':
            from app.agents.gemini import GeminiPlanner
            planner = GeminiPlanner(agents.model)
        else:
            planner = MockPlanner()
        orchestrator = AgentOrchestrator(
            planner,
            interval=agents.interval_seconds,
            timeout=agents.timeout_seconds,
            chat=getattr(conversation, 'chat', shared_chat),
        )
        autonomy_runner = AutonomyRunner(store, orchestrator)

    @asynccontextmanager
    async def lifespan(_app):
        if history is not None:
            try:
                await asyncio.to_thread(history.initialize)
                await asyncio.to_thread(store.attach_recorder, WorldRecorder(history))
            except Exception:
                raise RuntimeError('Persistence startup failed; check database configuration and access.') from None
        game_loop_task = (
            asyncio.create_task(simulator.run())
            if game_loop_enabled
            else None
        )
        telemetry_watchdog_task = (
            asyncio.create_task(telemetry_watchdog.run())
            if telemetry_watchdog_enabled
            else None
        )
        autonomy_task = (
            asyncio.create_task(autonomy_runner.run())
            if autonomy_runner is not None
            else None
        )
        try:
            yield
        finally:
            if autonomy_task:
                autonomy_task.cancel()
                await autonomy_task
            if telemetry_watchdog_task:
                telemetry_watchdog_task.cancel()
                await telemetry_watchdog_task
            if game_loop_task:
                game_loop_task.cancel()
                await game_loop_task

    app = FastAPI(title='Love Bugs', lifespan=lifespan)
    install_error_handlers(app)
    origins = os.getenv('FRONTEND_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173')
    app.add_middleware(CORSMiddleware, allow_origins=origins.split(','),
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])
    app.include_router(create_router(conversation))
    app.include_router(create_world_router(store))
    app.include_router(create_events_router(store))
    if history is not None:
        app.include_router(create_history_router(history, store))
    app.state.history = history
    app.state.world_store = store
    app.state.simulator = simulator
    app.state.simulator_enabled = simulator_enabled
    app.state.game_loop_enabled = game_loop_enabled
    app.state.telemetry_watchdog = telemetry_watchdog
    app.state.telemetry_watchdog_enabled = telemetry_watchdog_enabled
    app.state.orchestrator = orchestrator
    app.state.autonomy_runner = autonomy_runner
    app.state.autonomy_enabled = autonomy_enabled
    app.state.settings = config
    return app


app = create_app()
