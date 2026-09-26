"""Compose the live game, history recorder, simulator and spectator chat."""

import asyncio
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent_chat import DiscussionService, create_router
from app.api.errors import install_error_handlers
from app.api.events import create_events_router
from app.api.routes import create_world_router
from app.simulation.simulator import SimulationRunner
from app.state import WorldStore, default_world
from app.config import Settings
from app.persistence.store import Store
from app.persistence.recorder import WorldRecorder
from app.api.history import create_history_router
from uuid import uuid4


def create_app(service=None, world_store=None, run_simulator=None, *, settings=None):
    # Explicitly injected stores stay in-memory unless persistence is requested.
    persistent = world_store is None or settings is not None
    history = Store(settings or Settings()) if persistent else None
    if world_store is None:
        initial = default_world()
        initial['session_id'] = str(uuid4())
        store = WorldStore(initial)
    else:
        store = world_store
    simulator_enabled = world_store is None if run_simulator is None else run_simulator
    simulator = SimulationRunner(store)

    @asynccontextmanager
    async def lifespan(_app):
        if history is not None:
            try:
                await asyncio.to_thread(history.initialize)
                await asyncio.to_thread(store.attach_recorder, WorldRecorder(history))
            except Exception:
                raise RuntimeError('Persistence startup failed; check database configuration and access.') from None
        simulation_task = (
            asyncio.create_task(simulator.run())
            if simulator_enabled
            else None
        )
        try:
            yield
        finally:
            if simulation_task:
                simulation_task.cancel()
                await simulation_task

    app = FastAPI(title='Love Bugs', lifespan=lifespan)
    install_error_handlers(app)
    origins = os.getenv('FRONTEND_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173')
    app.add_middleware(CORSMiddleware, allow_origins=origins.split(','),
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])
    app.include_router(create_router(service if service is not None else DiscussionService()))
    app.include_router(create_world_router(store))
    app.include_router(create_events_router(store))
    if history is not None:
        app.include_router(create_history_router(history, store))
    app.state.history = history
    app.state.world_store = store
    app.state.simulator = simulator
    return app


app = create_app()
