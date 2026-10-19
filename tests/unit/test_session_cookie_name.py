from types import SimpleNamespace
from typing import Annotated

from fastapi import FastAPI, Security
from fastapi.testclient import TestClient

from app.api.deps import session_cookie


def _app_with_cookie_name(name: str) -> FastAPI:
    application = FastAPI()
    # Only the attribute the dependency reads; a real __Host- Settings needs a
    # deployed environment (tests/test_settings.py covers that validation).
    application.state.settings = SimpleNamespace(session_cookie_name=name)

    @application.get("/token")
    def token(
        value: Annotated[str | None, Security(session_cookie)] = None,
    ) -> dict[str, str | None]:
        return {"token": value}

    return application


def test_the_session_is_read_from_the_configured_cookie_name() -> None:
    client = TestClient(_app_with_cookie_name("__Host-lp_session"))
    client.cookies.set("__Host-lp_session", "token-1")

    assert client.get("/token").json() == {"token": "token-1"}


def test_the_default_name_is_ignored_once_another_name_is_configured() -> None:
    client = TestClient(_app_with_cookie_name("__Host-lp_session"))
    client.cookies.set("lottery_passport_session", "token-1")

    assert client.get("/token").json() == {"token": None}


def test_the_default_name_still_works_by_default() -> None:
    client = TestClient(_app_with_cookie_name("lottery_passport_session"))
    client.cookies.set("lottery_passport_session", "token-1")

    assert client.get("/token").json() == {"token": "token-1"}
