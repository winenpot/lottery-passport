from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_readiness_checker
from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.config import router as config_router
from app.api.v1.redemptions import router as redemptions_router
from app.api.v1.users import router as users_router
from app.application.ports import ReadinessChecker

router = APIRouter()
router.include_router(auth_router, prefix="/api/v1")
router.include_router(users_router, prefix="/api/v1")
router.include_router(config_router, prefix="/api/v1")
router.include_router(redemptions_router, prefix="/api/v1")
router.include_router(admin_router, prefix="/api/v1")


class HealthResponse(BaseModel):
    status: str


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    tags=["health"],
    summary="Process liveness",
    description="Always 200 once the process has started. Used by load balancers.",
)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=HealthResponse,
    tags=["health"],
    summary="Database readiness",
    description="503 if the database is unreachable. Used by the Render health check.",
    responses={503: {"description": "Database unreachable"}},
)
async def ready(
    readiness_checker: ReadinessChecker = Depends(get_readiness_checker),
) -> HealthResponse:
    if not await readiness_checker.check():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service unavailable",
        )
    return HealthResponse(status="ready")
