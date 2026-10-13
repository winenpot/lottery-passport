"""SMS delivery for authentication codes.

``ConsoleSmsSender`` is the default: no network call, just remembers the
last code (used in development and by the test suite, same as the previous
``DevelopmentEmailSender``). ``KavenegarSmsSender`` calls the vendor's
verify/lookup OTP route with stdlib ``urllib`` — this project has no async
HTTP client dependency, so the blocking call runs in a thread.

The API key sits in the request URL (Kavenegar's own API shape); it must
never be logged. Only the masked phone number and the HTTP status/response
body (which never contains the key) are logged on failure.
"""

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from app.application.authentication import SmsError, SmsSender
from app.domain.phone import mask_phone

logger = logging.getLogger(__name__)

KAVENEGAR_TIMEOUT_SECONDS = 10


@dataclass(slots=True)
class ConsoleSmsSender(SmsSender):
    """Dev/test sender: no network, remembers the last code it "sent"."""

    last_phone: str | None = None
    last_code: str | None = None
    last_purpose: str | None = None

    async def send_otp(self, phone: str, code: str, purpose: str) -> None:
        self.last_phone = phone
        self.last_code = code
        self.last_purpose = purpose
        logger.info(
            "otp issued (console) purpose=%s phone=%s", purpose, mask_phone(phone)
        )


class KavenegarSmsSender(SmsSender):
    """Calls Kavenegar's ``verify/lookup`` OTP route (pre-approved templates).

    One template per purpose (``login``, ``signup``): vendor template
    approval is per-template and can lag independently, so a rejected
    template for one purpose must not block the other (sms-otp-auth skill).
    """

    def __init__(self, api_key: str, template_by_purpose: dict[str, str]) -> None:
        self._api_key = api_key
        self._template_by_purpose = template_by_purpose

    async def send_otp(self, phone: str, code: str, purpose: str) -> None:
        template = self._template_by_purpose.get(purpose)
        if template is None:
            raise SmsError(f"no Kavenegar template configured for purpose {purpose!r}")
        receptor = phone.removeprefix("+")
        query = urllib.parse.urlencode(
            {"receptor": receptor, "token": code, "template": template}
        )
        url = f"https://api.kavenegar.com/v1/{self._api_key}/verify/lookup.json?{query}"
        try:
            await asyncio.to_thread(self._call, url)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            logger.warning(
                "kavenegar send failed purpose=%s phone=%s status=%s body=%s",
                purpose,
                mask_phone(phone),
                error.code,
                body,
            )
            raise SmsError(f"kavenegar returned HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            logger.warning(
                "kavenegar send failed purpose=%s phone=%s: %s",
                purpose,
                mask_phone(phone),
                error,
            )
            raise SmsError("kavenegar delivery failed") from error

    @staticmethod
    def _call(url: str) -> None:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(
            request, timeout=KAVENEGAR_TIMEOUT_SECONDS
        ) as response:
            body = response.read()
        payload = json.loads(body)
        return_status = payload.get("return", {}).get("status")
        if return_status != 200:
            message = payload.get("return", {}).get("message", "unknown error")
            raise SmsError(f"kavenegar rejected the request: {message}")
