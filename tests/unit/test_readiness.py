import pytest

from app.application.ports import ReadinessChecker


class AvailableDependency:
    async def check_connection(self) -> None:
        return


class UnavailableDependency:
    async def check_connection(self) -> None:
        raise ConnectionError("database unavailable")


@pytest.mark.asyncio
async def test_readiness_checker_accepts_available_dependency() -> None:
    checker = ReadinessChecker(AvailableDependency())

    assert await checker.check() is True


@pytest.mark.asyncio
async def test_readiness_checker_rejects_unavailable_dependency() -> None:
    checker = ReadinessChecker(UnavailableDependency())

    assert await checker.check() is False
