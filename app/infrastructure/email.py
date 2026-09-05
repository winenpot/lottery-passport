from dataclasses import dataclass

from app.application.authentication import EmailSender


@dataclass(slots=True)
class DevelopmentEmailSender(EmailSender):
    last_identifier: str | None = None
    last_code: str | None = None

    async def send_verification_code(self, identifier: str, code: str) -> None:
        self.last_identifier = identifier
        self.last_code = code


class UnavailableEmailSender(EmailSender):
    async def send_verification_code(self, identifier: str, code: str) -> None:
        raise RuntimeError("no production email provider is configured")
