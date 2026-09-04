import os

import pytest
from fastapi.testclient import TestClient

from app.app import create_app
from app.core.config import Settings


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/lottery_passport"
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def test_database_url() -> str:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        if os.getenv("CI"):
            pytest.fail("TEST_DATABASE_URL is required in CI")
        pytest.skip("TEST_DATABASE_URL is required for the PostgreSQL integration test")
    return database_url
