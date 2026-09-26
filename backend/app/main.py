"""Run one worker: each process start creates a new simulation session."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.concurrency import run_in_threadpool

from app.api.agent_chat import DiscussionService, create_router
from app.config import Settings
from app.game.cooperation import RuleViolation
from app.simulation.cooperation import CooperationDemo, SimulationCommand
from app.persistence.store import Store
from app.simulation.simulator import seed_session


def create_app(service=None, *, settings: Settings | None = None):
    """Accept legacy create_app(Settings(...)) and chat create_app(service).

    New callers can inject both using create_app(service=..., settings=...).
    """
    if isinstance(service, Settings):
        if settings is not None:
            raise TypeError("Settings supplied twice")
        settings, service = service, None
    settings = settings or Settings()
    store = Store(settings)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await run_in_threadpool(store.initialize)
            app.state.session_id = await run_in_threadpool(seed_session, store)
            app.state.demo = CooperationDemo(store, app.state.session_id)
        except Exception:
            raise RuntimeError("Persistence startup failed; check database configuration and access.") from None
        yield

    app = FastAPI(title="Love Bugs", lifespan=lifespan)
    if settings.frontend_origins is not None:
        origins = [origin.strip() for origin in settings.frontend_origins.split(",") if origin.strip()]
    else:
        origins = [settings.frontend_origin]
        if settings.frontend_origin == "http://localhost:5173":
            origins.append("http://127.0.0.1:5173")
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.include_router(create_router(service if service is not None else DiscussionService()))

    def is_chat(request):
        return request.url.path == "/agent-chat" or request.url.path.startswith("/agent-chat/")

    def error(code, message, status):
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        if is_chat(request):
            return await request_validation_exception_handler(request, exc)
        return error("INVALID_REQUEST", "Invalid request fields.", 400)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if is_chat(request):
            return await http_exception_handler(request, exc)
        return error("NOT_FOUND" if exc.status_code == 404 else "INVALID_REQUEST",
                     str(exc.detail), exc.status_code)

    @app.get("/world")
    def world():
        try:
            return store.world(app.state.demo.session_id)
        except Exception:
            return error("SUBSYSTEM_UNAVAILABLE", "Persistence unavailable.", 503)

    @app.get("/events")
    def events(limit: int = Query(default=100, ge=1, le=100)):
        try:
            session_id = app.state.demo.session_id
            return {"session_id": session_id, "events": store.recent_events(session_id, limit)}
        except Exception:
            return error("SUBSYSTEM_UNAVAILABLE", "Persistence unavailable.", 503)

    @app.get("/robots/{robot_id}/history")
    def robot_history(robot_id: str, limit: int = Query(default=100, ge=1, le=1000)):
        try:
            return store.robot_history(app.state.demo.session_id, robot_id, limit)
        except KeyError:
            return error("NOT_FOUND", "Unknown robot.", 404)
        except Exception:
            return error("SUBSYSTEM_UNAVAILABLE", "Persistence unavailable.", 503)

    @app.get("/simulation/cooperation")
    def cooperation():
        try:
            return app.state.demo.snapshot()
        except Exception:
            return error("SUBSYSTEM_UNAVAILABLE", "Persistence unavailable.", 503)

    @app.post("/simulation/cooperation/{operation}")
    def control(operation: str, command: SimulationCommand):
        if operation not in {"start", "advance", "reset"}:
            return error("NOT_FOUND", "Unknown simulation operation.", 404)
        try:
            result = app.state.demo.execute(operation, command)
            return result
        except RuleViolation as exc:
            return error("INVALID_STATE", str(exc), 409)
        except Exception:
            return error("SUBSYSTEM_UNAVAILABLE", "Persistence unavailable.", 503)

    @app.websocket("/events")
    async def snapshots(socket: WebSocket):
        await socket.accept()
        revision = None
        try:
            while True:
                snapshot = await run_in_threadpool(store.world, app.state.demo.session_id)
                identity = (snapshot["session_id"], snapshot["revision"])
                if identity != revision:
                    await socket.send_json({"type": "world_snapshot", "data": snapshot})
                    revision = identity
                try:
                    message = await asyncio.wait_for(socket.receive(), timeout=0.2)
                    if message["type"] == "websocket.disconnect":
                        break
                except asyncio.TimeoutError:
                    pass
        except WebSocketDisconnect:
            pass
        except Exception:
            await socket.close(code=1011, reason="Persistence unavailable")

    return app


app = create_app()
