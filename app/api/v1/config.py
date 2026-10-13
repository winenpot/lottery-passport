from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_app_config_service
from app.api.v1.schemas import ConfigResponse
from app.application.app_config import AppConfigService

router = APIRouter(tags=["config"])


@router.get(
    "/config",
    response_model=ConfigResponse,
    summary="Client configuration",
    description=(
        "No sign-in needed. Server time, the Tehran day and week keys and the "
        "limits clients must use instead of the phone clock, and the active "
        "lounges for the profile picker. Avatar/game catalogues are not "
        "included yet."
    ),
)
async def get_config(
    service: Annotated[AppConfigService, Depends(get_app_config_service)],
) -> ConfigResponse:
    return ConfigResponse.from_domain(await service.current())
