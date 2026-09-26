"""Read-only routes for the authoritative world snapshot."""

from fastapi import APIRouter

from app.schemas import WorldSnapshot
from app.state import WorldStore


def create_world_router(store: WorldStore) -> APIRouter:
    router = APIRouter(tags=['world'])

    @router.get('/world', response_model=WorldSnapshot)
    def world() -> WorldSnapshot:
        return store.snapshot()

    return router
