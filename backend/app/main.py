"""Local spectator-chat API. Game execution and hardware APIs remain separate."""

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
from app.state import WorldStore


def create_app(service=None, world_store=None, run_simulator=None):
    store = world_store if world_store is not None else WorldStore()
    simulator_enabled = world_store is None if run_simulator is None else run_simulator
    simulator = SimulationRunner(store)

    @asynccontextmanager
    async def lifespan(_app):
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
    app.state.world_store = store
    app.state.simulator = simulator
    return app


app = create_app()
