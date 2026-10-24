"""Encrypt-at-rest for the admin TOTP secret (app/domain/totp.py).

A TOTP secret is a long-lived key: unlike an OTP challenge code (short-lived,
only ever stored hashed, see app/infrastructure/authentication.py), leaking
it from a database dump lets an attacker generate valid codes forever
(docs/SECURITY.md T4). The algorithm itself stays stdlib-only (domain
layer); this is the one place that needs a real crypto library.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class SecretDecryptionError(ValueError):
    """Ciphertext does not decrypt with the configured key (wrong key,
    corrupted value, or tampering)."""


class SecretCipher:
    """Symmetric, authenticated encryption for one secret value at a time.

    ``passphrase`` is the configured ``ADMIN_TOTP_ENCRYPTION_KEY`` -- any
    length, any characters (same free-form shape as ``ADMIN_SESSION_SECRET``
    and the redemption pepper). Fernet needs exactly 32 url-safe base64
    bytes, so the passphrase is hashed down to that size; this is a fixed
    deterministic derivation, not a KDF with iterations, which is fine here
    because the input is already a long random secret, not a human password.
    """

    def __init__(self, passphrase: str) -> None:
        key = base64.urlsafe_b64encode(hashlib.sha256(passphrase.encode()).digest())
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode("utf-8")
        except InvalidToken as error:
            raise SecretDecryptionError(
                "could not decrypt: wrong ADMIN_TOTP_ENCRYPTION_KEY or corrupted value"
            ) from error
