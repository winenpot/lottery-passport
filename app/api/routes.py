from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from app.api.deps import get_readiness_checker
from app.api.errors import ApiError, ErrorResponse
from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.config import router as config_router
from app.api.v1.redemptions import router as redemptions_router
from app.api.v1.users import router as users_router
from app.application.ports import ReadinessChecker
from app.core.config import Settings

router = APIRouter()
router.include_router(auth_router, prefix="/api/v1")
router.include_router(users_router, prefix="/api/v1")
router.include_router(config_router, prefix="/api/v1")
router.include_router(redemptions_router, prefix="/api/v1")
router.include_router(admin_router, prefix="/api/v1")


class HealthResponse(BaseModel):
    status: str


class LivenessResponse(HealthResponse):
    version: str = Field(examples=["0.1.0"])
    commit: str | None = Field(
        description="Deployed git commit (first 7 characters); null when unknown.",
        examples=["579f8f1"],
    )
    environment: str = Field(examples=["demo"])


@router.get(
    "/health",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    tags=["health"],
    summary="Process liveness and deployed version",
    description=(
        "Always 200 once the process has started. Used by load balancers. "
        "`commit` tells a frontend developer whether their requested change is "
        "deployed yet."
    ),
)
async def health(request: Request) -> LivenessResponse:
    settings: Settings = request.app.state.settings
    return LivenessResponse(
        status="ok",
        version=request.app.version,
        commit=settings.git_commit[:7] if settings.git_commit else None,
        environment=settings.environment.lower(),
    )


@router.get(
    "/ready",
    response_model=HealthResponse,
    tags=["health"],
    summary="Database readiness",
    description="503 if the database is unreachable. Used by the Render health check.",
    responses={503: {"model": ErrorResponse, "description": "Database unreachable"}},
)
async def ready(
    readiness_checker: ReadinessChecker = Depends(get_readiness_checker),
) -> HealthResponse:
    if not await readiness_checker.check():
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SERVICE_UNAVAILABLE",
            "database unreachable",
        )
    return HealthResponse(status="ready")
