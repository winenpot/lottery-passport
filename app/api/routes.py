from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from app.api.deps import get_pepper_guard, get_readiness_checker
from app.api.errors import ApiError, ErrorResponse
from app.api.legal import router as legal_router
from app.api.v1.achievements import router as achievements_router
from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.avatars import router as avatars_router
from app.api.v1.challenges import router as challenges_router
from app.api.v1.config import router as config_router
from app.api.v1.mini_games import router as mini_games_router
from app.api.v1.redemptions import router as redemptions_router
from app.api.v1.teams import router as teams_router
from app.api.v1.users import router as users_router
from app.application.ports import ReadinessChecker
from app.application.redemption_codes import PepperGuard
from app.core.config import Settings

router = APIRouter()
router.include_router(auth_router, prefix="/api/v1")
router.include_router(users_router, prefix="/api/v1")
router.include_router(config_router, prefix="/api/v1")
router.include_router(redemptions_router, prefix="/api/v1")
router.include_router(avatars_router, prefix="/api/v1")
router.include_router(teams_router, prefix="/api/v1")
router.include_router(challenges_router, prefix="/api/v1")
router.include_router(mini_games_router, prefix="/api/v1")
router.include_router(achievements_router, prefix="/api/v1")
router.include_router(admin_router, prefix="/api/v1")
# A page, not an API resource: /legal/<version> (nginx forwards it here).
router.include_router(legal_router)


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
    summary="Database and pepper-guard readiness",
    description=(
        "503 if the database is unreachable, or if an ACTIVE code batch's pepper "
        "fingerprint does not match the pepper this process is running with. Used "
        "by deploy checks and uptime probes."
    ),
    responses={
        503: {
            "model": ErrorResponse,
            "description": "Database unreachable, or a pepper mismatch",
        }
    },
)
async def ready(
    readiness_checker: ReadinessChecker = Depends(get_readiness_checker),
    pepper_guard: PepperGuard = Depends(get_pepper_guard),
) -> HealthResponse:
    if not await readiness_checker.check():
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SERVICE_UNAVAILABLE",
            "database unreachable",
        )
    if not await pepper_guard.check():
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SERVICE_UNAVAILABLE",
            "an active code batch's pepper does not match the configured pepper",
        )
    return HealthResponse(status="ready")
