"""Additive historical reads; /world and WebSocket /events stay live."""
from fastapi import APIRouter, Query
from app.api.errors import ApiError


def create_history_router(history, world_store):
    router = APIRouter(tags=['history'])

    def session(value):
        return value or world_store.snapshot().session_id

    @router.get('/events')
    def events(session_id: str | None = None, limit: int = Query(100, ge=1, le=1000)):
        selected = session(session_id)
        try:
            return {'session_id': selected, 'events': history.recent_events(selected, limit)}
        except Exception:
            raise ApiError(503, 'PERSISTENCE_UNAVAILABLE', 'History unavailable.') from None

    @router.get('/robots/{robot_id}/history')
    def robot_history(robot_id: str, session_id: str | None = None,
                      limit: int = Query(100, ge=1, le=1000)):
        try:
            return history.robot_history(session(session_id), robot_id, limit)
        except KeyError:
            raise ApiError(404, 'NOT_FOUND', 'Unknown session or robot.') from None
        except Exception:
            raise ApiError(503, 'PERSISTENCE_UNAVAILABLE', 'History unavailable.') from None

    return router
