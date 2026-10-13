import logging
from collections import defaultdict, deque
from threading import Lock
from time import monotonic
from uuid import uuid4

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import error_bytes, note_error_code, request_id_from_scope

request_logger = logging.getLogger("lottery_passport.http")


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        requests: int,
        window_seconds: int,
    ) -> None:
        self.app = app
        self.requests = requests
        self.window_seconds = window_seconds
        self._request_times: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in {"/health", "/ready"}:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_key = client[0] if client else "unknown"
        now = monotonic()
        limited = False
        with self._lock:
            request_times = self._request_times[client_key]
            while request_times and now - request_times[0] >= self.window_seconds:
                request_times.popleft()
            if len(request_times) >= self.requests:
                limited = True
            else:
                request_times.append(now)

        if limited:
            await self._send_limited(scope, send)
            return

        await self.app(scope, receive, send)

    async def _send_limited(self, scope: Scope, send: Send) -> None:
        note_error_code(scope, "RATE_LIMITED")
        body = error_bytes(
            "RATE_LIMITED", "rate limit exceeded", request_id_from_scope(scope)
        )
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(self.window_seconds).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


CSRF_HEADER = "X-Requested-With"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CsrfMiddleware:
    """Reject cookie-authenticated writes that a foreign page could forge.

    The session cookie may be ``SameSite=None`` (frontend and API on different
    sites), so the browser attaches it to cross-site requests too. A write
    that carries the session cookie must therefore:

    * send the ``X-Requested-With`` header (any value). A plain HTML form or
      ``<img>`` cannot set it, and a cross-site ``fetch`` that sets it needs a
      CORS preflight that only our allowed origins pass;
    * if the browser sent ``Origin``, have it on the CORS allow-list.

    Requests without the session cookie (sign-in, anonymous calls) are not
    affected: there is no session to ride on. OWASP: "custom request header"
    and "verifying origin with standard headers".
    """

    def __init__(
        self,
        app: ASGIApp,
        cookie_name: str,
        allowed_origins: list[str],
    ) -> None:
        self.app = app
        self.cookie_name = cookie_name
        self.any_origin = allowed_origins == ["*"]
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        cookie = headers.get("cookie", "")
        has_session = any(
            part.strip().startswith(f"{self.cookie_name}=")
            for part in cookie.split(";")
        )
        if has_session:
            origin = headers.get("origin")
            if not headers.get(CSRF_HEADER):
                await self._reject(scope, send, f"missing {CSRF_HEADER} header")
                return
            if origin and not self.any_origin and origin not in self.allowed_origins:
                await self._reject(scope, send, "origin not allowed")
                return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, send: Send, message: str) -> None:
        note_error_code(scope, "CSRF_REJECTED")
        request_logger.warning(
            "csrf_rejected",
            extra={
                "request_id": request_id_from_scope(scope),
                "method": scope.get("method"),
                "path": scope.get("path"),
                "reason": message,
                "origin": Headers(scope=scope).get("origin"),
            },
        )
        body = error_bytes("CSRF_REJECTED", message, request_id_from_scope(scope))
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        # Read by the error handlers so the body and the X-Request-ID header agree.
        scope.setdefault("state", {})["request_id"] = request_id
        started_at = monotonic()
        status_code = 500

        async def send_with_logging(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_logging)
        except Exception:
            request_logger.error(
                "request_failed",
                extra=self._log_fields(scope, request_id, status_code, started_at),
                exc_info=False,
            )
            raise
        else:
            request_logger.info(
                "request_completed",
                extra=self._log_fields(scope, request_id, status_code, started_at),
            )

    @staticmethod
    def _log_fields(
        scope: Scope,
        request_id: str,
        status_code: int,
        started_at: float,
    ) -> dict[str, object]:
        client = scope.get("client")
        fields: dict[str, object] = {
            "request_id": request_id,
            "method": scope.get("method", "UNKNOWN"),
            "path": scope.get("path", ""),
            "status_code": status_code,
            "latency_ms": round((monotonic() - started_at) * 1000, 2),
            "client_ip": client[0] if client else "unknown",
        }
        error_code = (scope.get("state") or {}).get("error_code")
        if error_code is not None:
            fields["error_code"] = error_code
        return fields
