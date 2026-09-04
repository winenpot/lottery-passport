from typing import Protocol


class ReadinessPort(Protocol):
    async def check_connection(self) -> None:
        """Verify that a required persistence dependency is available."""


class ReadinessChecker:
    def __init__(self, dependency: ReadinessPort) -> None:
        self._dependency = dependency

    async def check(self) -> bool:
        try:
            await self._dependency.check_connection()
        except Exception:
            return False
        return True
