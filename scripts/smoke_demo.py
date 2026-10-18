"""Walk the whole frontend path against a running API and print pass/fail.

Usage (stdlib only, nothing to install)::

    uv run python -m scripts.smoke_demo \\
        --base-url https://staging.torshx.com \\
        --origin https://staging.torshx.com \\
        [--code TO-XXX-XXX-XXX]

It behaves like the browser app: sends ``Origin``, keeps the session cookie,
adds ``X-Requested-With`` on writes. Sign-in uses a random ``0969`` test
number (demo/staging only: the API returns the code in ``test_code``), so run
it against staging, never production. ``--code`` redeems one demo code twice
(second call must be an idempotent replay); without it that step is skipped.

Exit status 1 if any step fails. The first request is timed on its own.
"""

import argparse
import http.cookiejar
import json
import random
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

LOCAL_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")
EVIL_ORIGIN = "https://evil.example"
CSRF_HEADER = "X-Requested-With"


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    text: str
    seconds: float

    def json(self) -> dict[str, Any]:
        try:
            value = json.loads(self.text)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def error_code(self) -> str | None:
        error = self.json().get("error")
        return error.get("code") if isinstance(error, dict) else None


class Client:
    def __init__(self, base_url: str, origin: str, timeout: float = 90.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.origin = origin
        self.timeout = timeout
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )

    def call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        origin: str | None = None,
        csrf: bool = False,
        extra: dict[str, str] | None = None,
    ) -> Reply:
        headers = {"Accept": "application/json"}
        chosen_origin = self.origin if origin is None else origin
        if chosen_origin:
            headers["Origin"] = chosen_origin
        if csrf:
            headers[CSRF_HEADER] = "smoke"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        headers.update(extra or {})
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        started = time.monotonic()
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                status, raw, received = (
                    response.status,
                    response.read(),
                    response.headers,
                )
        except urllib.error.HTTPError as error:
            status, raw, received = error.code, error.read(), error.headers
        seconds = time.monotonic() - started
        return Reply(
            status,
            {key.lower(): value for key, value in received.items()},
            raw.decode("utf-8", "replace"),
            seconds,
        )

    def session_cookie(self) -> http.cookiejar.Cookie | None:
        for cookie in self.cookies:
            if cookie.has_nonstandard_attr("HttpOnly"):
                return cookie
        return next(iter(self.cookies), None)


def random_test_phone(rng: random.Random) -> str:
    """A 0969 test number; random so reruns never hit the resend cooldown."""
    return "0969" + "".join(str(rng.randrange(10)) for _ in range(7))


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, ok: bool | None, name: str, detail: str = "") -> bool:
        status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        self.rows.append((status, name, detail))
        print(f"{status:<5} {name:<44} {detail}", flush=True)
        return bool(ok)

    @property
    def failed(self) -> int:
        return sum(1 for status, _, _ in self.rows if status == "FAIL")


def preflight(client: Client, origin: str, path: str, method: str) -> Reply:
    return client.call(
        "OPTIONS",
        path,
        origin=origin,
        extra={
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": f"content-type,{CSRF_HEADER.lower()}",
        },
    )


def run(client: Client, report: Report, code: str | None, rng: random.Random) -> None:
    add = report.add

    # 1. Wake the service and show what is deployed.
    health = client.call("GET", "/health")
    body = health.json()
    add(
        health.status == 200 and body.get("status") == "ok",
        "GET /health (first call, cold start)",
        f"{health.seconds:.1f}s commit={body.get('commit')} "
        f"version={body.get('version')} env={body.get('environment')}",
    )
    ready = client.call("GET", "/ready")
    add(ready.status == 200, "GET /ready (database reachable)", f"{ready.seconds:.2f}s")
    config = client.call("GET", "/api/v1/config")
    cfg = config.json()
    add(
        config.status == 200 and "terms_version" in cfg and "venues" in cfg,
        "GET /api/v1/config",
        f"terms={cfg.get('terms_version')} venues={len(cfg.get('venues') or [])}",
    )

    # 2. CORS.
    for origin in dict.fromkeys((client.origin, *LOCAL_ORIGINS)):
        reply = preflight(client, origin, "/api/v1/me", "PATCH")
        add(
            reply.status == 200
            and reply.headers.get("access-control-allow-origin") == origin
            and reply.headers.get("access-control-allow-credentials") == "true"
            and CSRF_HEADER.lower()
            in reply.headers.get("access-control-allow-headers", "").lower(),
            f"CORS preflight allowed: {origin}",
            f"HTTP {reply.status}",
        )
    refused = preflight(client, EVIL_ORIGIN, "/api/v1/me", "PATCH")
    add(
        "access-control-allow-origin" not in refused.headers,
        f"CORS preflight refused: {EVIL_ORIGIN}",
        f"HTTP {refused.status}",
    )

    # 3. One error shape everywhere.
    missing = client.call("GET", "/api/v1/nope")
    add(
        missing.status == 404
        and missing.error_code() == "NOT_FOUND"
        and missing.json()["error"].get("request_id")
        == missing.headers.get("x-request-id"),
        "404 uses the error envelope + request_id",
        f"HTTP {missing.status} {missing.error_code()}",
    )
    invalid = client.call("POST", "/api/v1/auth/request", {})
    fields = (invalid.json().get("error") or {}).get("fields") or []
    add(
        invalid.status == 422
        and invalid.error_code() == "VALIDATION_FAILED"
        and bool(fields),
        "422 VALIDATION_FAILED lists the fields",
        f"HTTP {invalid.status} fields={[f.get('field') for f in fields]}",
    )
    wrong = client.call("DELETE", "/api/v1/config")
    add(
        wrong.status == 405 and wrong.error_code() == "METHOD_NOT_ALLOWED",
        "405 uses the error envelope",
        f"HTTP {wrong.status} {wrong.error_code()}",
    )
    anonymous = client.call("GET", "/api/v1/me")
    add(
        anonymous.status == 401 and anonymous.error_code() == "AUTH_REQUIRED",
        "GET /me without a session -> 401 AUTH_REQUIRED",
        f"HTTP {anonymous.status}",
    )

    # 4. Sign in with a test number.
    phone = random_test_phone(rng)
    requested = client.call("POST", "/api/v1/auth/request", {"identifier": phone})
    test_code = requested.json().get("test_code")
    add(
        requested.status == 202 and bool(test_code),
        "POST /auth/request (test number returns test_code)",
        f"HTTP {requested.status} code_length={requested.json().get('code_length')}",
    )
    if not test_code:
        add(None, "remaining signed-in steps", "no test_code; is this the demo?")
        return
    wrong_code = client.call(
        "POST", "/api/v1/auth/verify", {"identifier": phone, "code": "000000"}
    )
    add(
        wrong_code.status == 401 and wrong_code.error_code() == "OTP_INVALID",
        "POST /auth/verify wrong code -> 401 OTP_INVALID",
        f"HTTP {wrong_code.status} {wrong_code.error_code()}",
    )
    verified = client.call(
        "POST", "/api/v1/auth/verify", {"identifier": phone, "code": test_code}
    )
    set_cookie = verified.headers.get("set-cookie", "")
    add(
        verified.status == 200 and "httponly" in set_cookie.lower(),
        "POST /auth/verify (session cookie set, HttpOnly)",
        f"HTTP {verified.status} {_cookie_flags(set_cookie)}",
    )
    reused = client.call(
        "POST",
        "/api/v1/auth/verify",
        {"identifier": phone, "code": test_code},
        csrf=True,
    )
    add(reused.status == 401, "code cannot be used twice", f"HTTP {reused.status}")

    # 5. Session, CSRF, profile.
    me = client.call("GET", "/api/v1/me")
    add(
        me.status == 200 and me.json().get("profile_complete") is False,
        "GET /me with the cookie",
        f"HTTP {me.status} (cookie sent back by the client)",
    )
    no_header = client.call("PATCH", "/api/v1/me", {})
    add(
        no_header.status == 403 and no_header.error_code() == "CSRF_REJECTED",
        f"PATCH /me without {CSRF_HEADER} -> 403 CSRF_REJECTED",
        f"HTTP {no_header.status}",
    )
    foreign = client.call("PATCH", "/api/v1/me", {}, origin=EVIL_ORIGIN, csrf=True)
    add(
        foreign.status == 403 and foreign.error_code() == "CSRF_REJECTED",
        "PATCH /me from a foreign Origin -> 403",
        f"HTTP {foreign.status}",
    )
    too_early = client.call(
        "POST", "/api/v1/redemptions", {"code": code or "hello"}, csrf=True
    )
    add(
        too_early.status == 403 and too_early.error_code() == "TERMS_NOT_ACCEPTED",
        "POST /redemptions before the profile is done -> 403",
        f"HTTP {too_early.status} {too_early.error_code()}",
    )
    nickname = "Smoke" + "".join(str(rng.randrange(10)) for _ in range(6))
    profile = client.call(
        "PATCH",
        "/api/v1/me",
        {"nickname": nickname, "accept_terms_version": cfg.get("terms_version")},
        csrf=True,
    )
    add(
        profile.status == 200 and profile.json().get("profile_complete") is True,
        "PATCH /me nickname + terms -> profile_complete",
        f"HTTP {profile.status} {profile.error_code() or ''}",
    )
    venues = cfg.get("venues") or []
    if venues:
        picked = client.call(
            "PATCH", "/api/v1/me", {"home_venue_id": venues[0]["id"]}, csrf=True
        )
        add(
            picked.status == 200
            and picked.json().get("home_venue_id") == venues[0]["id"],
            "PATCH /me home_venue_id from /config venues",
            f"HTTP {picked.status} {venues[0]['id']}",
        )
    else:
        add(None, "PATCH /me home_venue_id from /config venues", "no venues yet")
    bad_venue = client.call(
        "PATCH", "/api/v1/me", {"home_venue_id": "no-such-lounge"}, csrf=True
    )
    add(
        bad_venue.status == 422 and bad_venue.error_code() == "CATALOGUE_UNKNOWN",
        "PATCH /me unknown lounge -> 422 CATALOGUE_UNKNOWN",
        f"HTTP {bad_venue.status}",
    )
    bad_nickname = client.call("PATCH", "/api/v1/me", {"nickname": "a b"}, csrf=True)
    add(
        bad_nickname.status == 422 and bad_nickname.error_code() == "NICKNAME_INVALID",
        "PATCH /me bad nickname -> 422 NICKNAME_INVALID",
        f"HTTP {bad_nickname.status}",
    )

    # 6. Scanning.
    if code is None:
        add(None, "POST /redemptions (first + replay)", "pass --code to test")
    else:
        garbage = client.call(
            "POST", "/api/v1/redemptions", {"code": "hello"}, csrf=True
        )
        add(
            garbage.status == 400 and garbage.error_code() == "CODE_MALFORMED",
            "POST /redemptions garbage -> 400 CODE_MALFORMED",
            f"HTTP {garbage.status} {garbage.error_code()}",
        )
        first = client.call("POST", "/api/v1/redemptions", {"code": code}, csrf=True)
        add(
            first.status == 200 and first.json().get("replayed") is False,
            "POST /redemptions first use",
            f"HTTP {first.status} {first.error_code() or ''} "
            f"coins={first.json().get('coins_awarded')}",
        )
        replay = client.call("POST", "/api/v1/redemptions", {"code": code}, csrf=True)
        add(
            replay.status == 200 and replay.json().get("replayed") is True,
            "POST /redemptions replay is idempotent",
            f"HTTP {replay.status}",
        )
        wallet = client.call("GET", "/api/v1/me/wallet")
        add(
            wallet.status == 200
            and wallet.json().get("balance") == first.json().get("coin_balance"),
            "GET /me/wallet matches the redemption",
            f"balance={wallet.json().get('balance')}",
        )

    # 7. Sign out.
    logout = client.call("POST", "/api/v1/auth/logout", csrf=True)
    after = client.call("GET", "/api/v1/me")
    add(
        logout.status == 204 and after.status == 401,
        "POST /auth/logout, then /me -> 401",
        f"logout HTTP {logout.status}, me HTTP {after.status}",
    )


def _cookie_flags(set_cookie: str) -> str:
    parts = [part.strip() for part in set_cookie.split(";")[1:]]
    return " ".join(part for part in parts if not part.lower().startswith("max-age"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--origin",
        required=True,
        help="the frontend origin to send, e.g. https://staging.torshx.com",
    )
    parser.add_argument("--code", help="one demo code to redeem (twice: first, replay)")
    arguments = parser.parse_args(argv)
    if "staging" not in arguments.base_url and "localhost" not in arguments.base_url:
        print("note: this signs in with 0969 test numbers; use it on staging only")
    report = Report()
    run(
        Client(arguments.base_url, arguments.origin),
        report,
        arguments.code,
        random.Random(),
    )
    passed = sum(1 for status, _, _ in report.rows if status == "PASS")
    skipped = sum(1 for status, _, _ in report.rows if status == "SKIP")
    print(f"\n{passed} passed, {report.failed} failed, {skipped} skipped")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
