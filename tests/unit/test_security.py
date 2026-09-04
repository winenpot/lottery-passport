import pytest
from fastapi import HTTPException

from app.api.security import require_api_key
from app.core.config import Settings


def test_api_key_is_checked_without_plaintext_logging() -> None:
    settings = Settings(api_key="test-secret")

    require_api_key(settings, "test-secret")

    with pytest.raises(HTTPException) as error:
        require_api_key(settings, "wrong-secret")
    assert error.value.status_code == 401
