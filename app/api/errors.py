"""One error shape for every response, so the frontend switches on codes.

Response body::

    {"error": {"code": "CODE_MISTYPED", "message": "...", "request_id": "..."}}

``code`` is stable and documented in ``docs/API_CONTRACT.md``; ``message``
is English developer text. User-facing (Persian) copy belongs to the
frontend, keyed by ``code``. ``request_id`` equals the ``X-Request-ID``
response header and the ``request_id`` in our logs: quote it when reporting a
problem. ``VALIDATION_FAILED`` also carries ``fields``.
"""

import json
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

# Statuses FastAPI/Starlette raise by themselves (unknown path, wrong method,
# our own 503 from /ready) mapped to documented codes.
_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


class FieldError(BaseModel):
    field: str = Field(examples=["body.identifier"])
    message: str = Field(examples=["Field required"])
    type: str = Field(examples=["missing"])


class ErrorDetail(BaseModel):
    code: str = Field(examples=["CODE_MISTYPED"])
    message: str = Field(examples=["One character looks mistyped; check the code."])
    request_id: str | None = Field(
        default=None,
        description="Same as the X-Request-ID header; quote it in bug reports.",
    )
    fields: list[FieldError] | None = Field(
        default=None, description="Only on VALIDATION_FAILED."
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Structured extra data for a specific error code, for example "
            "``{required, have}`` on TEAM/FLAVOR errors. Absent otherwise."
        ),
    )


class ErrorResponse(BaseModel):
    """The shape of every error body; see docs/API_CONTRACT.md#errors.

    ``responses={...}`` on a route should reference this model so /docs and
    the generated OpenAPI schema show the real envelope, not FastAPI's
    default ``{"detail": "..."}``.
    """

    error: ErrorDetail


def request_id_from_scope(scope: Scope) -> str | None:
    state = scope.get("state")
    if isinstance(state, Mapping):
        value = state.get("request_id")
        return str(value) if value is not None else None
    return None


def note_error_code(scope: Scope, code: str) -> None:
    """Let the request log line carry the error code (``error_code``)."""
    state = scope.get("state")
    if isinstance(state, dict):
        state["error_code"] = code


def error_body(
    code: str,
    message: str,
    request_id: str | None,
    fields: list[dict[str, str]] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail: dict[str, Any] = {"code": code, "message": message}
    if request_id is not None:
        detail["request_id"] = request_id
    if fields is not None:
        detail["fields"] = fields
    if details is not None:
        detail["details"] = details
    return {"error": detail}


def error_bytes(code: str, message: str, request_id: str | None) -> bytes:
    """For middleware, which answers before FastAPI's handlers exist."""
    return json.dumps(
        error_body(code, message, request_id), separators=(",", ":")
    ).encode()


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        retry_after_seconds: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after_seconds = retry_after_seconds
        self.details = details


async def api_error_handler(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, ApiError):  # pragma: no cover - registered for ApiError
        raise error
    headers = (
        {"Retry-After": str(error.retry_after_seconds)}
        if error.retry_after_seconds is not None
        else None
    )
    note_error_code(request.scope, error.code)
    return JSONResponse(
        status_code=error.status_code,
        content=error_body(
            error.code,
            error.message,
            request_id_from_scope(request.scope),
            details=error.details,
        ),
        headers=headers,
    )


async def http_error_handler(request: Request, error: Exception) -> JSONResponse:
    """Unknown path (404), wrong method (405) and any bare HTTPException."""
    if not isinstance(error, StarletteHTTPException):  # pragma: no cover
        raise error
    code = _HTTP_CODES.get(error.status_code, f"HTTP_{error.status_code}")
    message = {
        404: "no such route",
        405: "method not allowed for this route",
        503: "service unavailable",
    }.get(error.status_code, str(error.detail))
    note_error_code(request.scope, code)
    return JSONResponse(
        status_code=error.status_code,
        content=error_body(code, message, request_id_from_scope(request.scope)),
        headers=dict(error.headers) if error.headers else None,
    )


async def validation_error_handler(request: Request, error: Exception) -> JSONResponse:
    """422 with the offending fields. The submitted values are never echoed."""
    if not isinstance(error, RequestValidationError):  # pragma: no cover
        raise error
    fields = [
        {
            "field": ".".join(str(part) for part in item["loc"]),
            "message": str(item["msg"]),
            "type": str(item["type"]),
        }
        for item in error.errors()
    ]
    note_error_code(request.scope, "VALIDATION_FAILED")
    return JSONResponse(
        status_code=422,
        content=error_body(
            "VALIDATION_FAILED",
            "request validation failed",
            request_id_from_scope(request.scope),
            fields,
        ),
    )


async def unhandled_error_handler(request: Request, __: Exception) -> JSONResponse:
    """Last resort: same envelope, no internals. The exception is still logged."""
    return JSONResponse(
        status_code=500,
        content=error_body(
            "INTERNAL_ERROR", "internal error", request_id_from_scope(request.scope)
        ),
    )


def document_validation_errors(schema: dict[str, Any]) -> dict[str, Any]:
    """Point every 422 in an OpenAPI schema at ``ErrorResponse``.

    FastAPI documents its built-in ``{"detail": [...]}`` 422; our handler
    returns the envelope instead, so the generated contract must say so.
    """
    components = schema.get("components", {}).get("schemas", {})
    reference = {"$ref": "#/components/schemas/ErrorResponse"}
    for methods in schema.get("paths", {}).values():
        for operation in methods.values():
            response = operation.get("responses", {}).get("422")
            if response is None:
                continue
            content = response.get("content", {}).get("application/json")
            if content is not None and content.get("schema", {}).get(
                "$ref", ""
            ).endswith("HTTPValidationError"):
                response["description"] = "VALIDATION_FAILED (see error.fields)"
                content["schema"] = reference
    for name in ("HTTPValidationError", "ValidationError"):
        components.pop(name, None)
    return schema
