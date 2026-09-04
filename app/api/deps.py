from typing import cast

from fastapi import Request

from app.application.ports import ReadinessChecker


def get_readiness_checker(request: Request) -> ReadinessChecker:
    return cast(ReadinessChecker, request.app.state.readiness_checker)
