"""KavenegarSmsSender: URL construction only (no real network call)."""

import urllib.parse

from app.infrastructure.sms import KavenegarSmsSender


def test_lookup_url_sends_the_same_code_as_both_token_and_token2() -> None:
    # Our template text (docs/OPERATIONS.md) uses %token twice in one
    # message. If the approved template ends up registered as %token +
    # %token2 instead (Kavenegar rejected a repeated %token), this must
    # already send both -- with no second deploy to notice and fix it.
    sender = KavenegarSmsSender(api_key="k3y", template_by_purpose={"login": "login"})

    url = sender._lookup_url("+989121234567", "483920", "login")

    assert url.startswith("https://api.kavenegar.com/v1/k3y/verify/lookup.json?")
    query = urllib.parse.parse_qs(url.split("?", 1)[1])
    assert query["receptor"] == ["989121234567"]  # leading + stripped
    assert query["token"] == ["483920"]
    assert query["token2"] == ["483920"]
    assert query["template"] == ["login"]
