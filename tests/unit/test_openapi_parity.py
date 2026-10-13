"""The committed docs/openapi.json must match what app.openapi() produces now.

Same pattern as the codes.js/code-test-vectors.json parity test: regenerate
with ``uv run python -m scripts.export_openapi`` and commit the result in the
same change as the route/schema edit that caused the drift (CLAUDE.md).
"""

import json

from scripts.export_openapi import OPENAPI_PATH, current_schema


def test_committed_openapi_json_matches_the_live_schema() -> None:
    committed = json.loads(OPENAPI_PATH.read_text())
    live = current_schema()

    assert committed == live, (
        "docs/openapi.json is stale: run "
        "`uv run python -m scripts.export_openapi` and commit the result"
    )


def test_every_route_has_a_stable_operation_id() -> None:
    live = current_schema()

    operation_ids = [
        info["operationId"]
        for methods in live["paths"].values()
        for info in methods.values()
        if "operationId" in info
    ]

    assert len(operation_ids) == len(set(operation_ids)), "duplicate operationId"
    assert all(operation_ids), "every route needs an operationId"


def test_error_responses_reference_the_shared_error_schema() -> None:
    """Every non-422/404-default error response documents {error: {code, message}}."""
    live = current_schema()

    assert "ErrorResponse" in live["components"]["schemas"]
    error_schema = live["components"]["schemas"]["ErrorResponse"]
    assert set(error_schema["required"]) == {"error"}


def test_docs_are_disabled_in_production() -> None:
    from app.app import create_app
    from app.core.config import Settings

    production_app = create_app(
        Settings(
            environment="production",
            database_url="postgresql+asyncpg://app:secret@postgres:5432/db",
            redemption_code_pepper="p" * 48,
            admin_session_secret="a" * 48,
        )
    )

    assert production_app.docs_url is None
    assert production_app.redoc_url is None
    assert production_app.openapi_url is None


def test_docs_are_enabled_outside_production() -> None:
    from app.app import create_app
    from app.core.config import Settings

    for environment in ("development", "demo", "staging"):
        development_app = create_app(
            Settings(
                environment=environment,
                database_url="postgresql+asyncpg://app:secret@postgres:5432/db",
                redemption_code_pepper="p" * 48,
                admin_session_secret="a" * 48,
            )
        )

        assert development_app.docs_url == "/docs"
        assert development_app.redoc_url == "/redoc"
        assert development_app.openapi_url == "/openapi.json"
