import hashlib
import secrets
from datetime import UTC, datetime

from app.application.authentication import AuthenticationCodeGenerator, Clock


class SecureAuthenticationCodeGenerator(AuthenticationCodeGenerator):
    def generate(self) -> tuple[str, str, str]:
        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_urlsafe(16)
        return code, salt, self.hash_code(code, salt)

    def hash_code(self, code: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)
