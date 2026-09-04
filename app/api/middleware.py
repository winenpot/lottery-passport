import logging
from collections import defaultdict, deque
from threading import Lock
from time import monotonic
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
            await self._send_limited(send)
            return

        await self.app(scope, receive, send)

    async def _send_limited(self, send: Send) -> None:
        body = b'{"detail":"rate limit exceeded"}'
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


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
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
        return {
            "request_id": request_id,
            "method": scope.get("method", "UNKNOWN"),
            "path": scope.get("path", ""),
            "status_code": status_code,
            "latency_ms": round((monotonic() - started_at) * 1000, 2),
            "client_ip": client[0] if client else "unknown",
        }
