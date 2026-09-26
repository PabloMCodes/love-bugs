"""Local spectator-chat API. Game execution and hardware APIs remain separate."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent_chat import DiscussionService, create_router


def create_app(service=None):
    app = FastAPI(title='Love Bugs')
    origins = os.getenv('FRONTEND_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173')
    app.add_middleware(CORSMiddleware, allow_origins=origins.split(','),
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])
    app.include_router(create_router(service if service is not None else DiscussionService()))
    return app


app = create_app()
