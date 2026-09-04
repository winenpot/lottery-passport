import pytest

from app.core.config import Settings
from app.infrastructure.postgres.database import PostgreSQLAdapter


@pytest.mark.asyncio
async def test_database_connectivity(test_database_url: str) -> None:
    database = PostgreSQLAdapter(Settings(database_url=test_database_url))
    try:
        await database.check_connection()
    finally:
        await database.dispose()
