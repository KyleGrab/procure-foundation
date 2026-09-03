from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready() -> dict:
    # Phase 1: liveness only. Phase 2+ adds a real DB/Redis ping here once there's a dependency
    # worth reporting on beyond "the process is running."
    return {"status": "ready"}
