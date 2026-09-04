import json
import logging

from app.core.logging import JsonFormatter


def test_json_formatter_contains_safe_request_fields() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request_completed",
        args=(),
        exc_info=None,
    )
    record.request_id = "request-id"
    record.method = "GET"
    record.path = "/health"
    record.status_code = 200
    record.latency_ms = 1.25
    record.client_ip = "127.0.0.1"
    record.api_key = "must-not-appear"

    output = JsonFormatter().format(record)
    payload = json.loads(output)

    assert payload["request_id"] == "request-id"
    assert payload["status_code"] == 200
    assert "api_key" not in payload
    assert "must-not-appear" not in output
