"""Read-only routes for the authoritative world snapshot."""

from fastapi import APIRouter

from app.api.errors import ApiError
from app.schemas import RobotTask, TaskRequest, WorldSnapshot
from app.state import WorldStateError, WorldStore


ERROR_STATUS_CODES = {
    'INVALID_REQUEST': 400,
    'NOT_FOUND': 404,
    'REQUEST_ID_CONFLICT': 409,
    'GAME_NOT_RUNNING': 409,
    'GAME_COMPLETED': 409,
    'ROBOT_BUSY': 409,
    'ROBOT_STOPPED': 409,
    'ROBOT_UNAVAILABLE': 409,
}


def translate_world_error(error: WorldStateError) -> ApiError:
    return ApiError(
        ERROR_STATUS_CODES.get(error.code, 500),
        error.code,
        error.message,
    )


def create_world_router(store: WorldStore) -> APIRouter:
    router = APIRouter(tags=['world'])

    @router.get('/world', response_model=WorldSnapshot)
    def world() -> WorldSnapshot:
        return store.snapshot()

    @router.post('/game/start', response_model=WorldSnapshot)
    def start_game() -> WorldSnapshot:
        try:
            return store.start_game()
        except WorldStateError as error:
            raise translate_world_error(error) from error

    @router.post('/tasks', response_model=RobotTask, status_code=202)
    def create_task(request: TaskRequest) -> RobotTask:
        try:
            return store.assign_move_task(request)
        except WorldStateError as error:
            raise translate_world_error(error) from error

    return router
