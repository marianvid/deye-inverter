"""The interface password (one password, set at the first visit) and the session secret."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from deye_inverter.ports import KeyValueStore

PASSWORD_KEY = "password_hash"
SECRET_KEY = "session_secret"
MIN_PASSWORD_LENGTH = 8
SCRYPT = {"n": 2**14, "r": 8, "p": 1}


class PasswordError(ValueError):
    """The chosen interface password is too short."""


class PasswordService:
    """Stores the interface password as a salted scrypt hash and keeps the session cookie secret."""

    def __init__(self, store: KeyValueStore) -> None:
        self._store = store

    def is_set(self) -> bool:
        """True once a password has been chosen at the first visit."""
        return self._store.get(PASSWORD_KEY) is not None

    def set(self, password: str) -> None:
        """Saves the password's salted hash; raises :class:`PasswordError` if it is shorter than 8
        characters."""
        if len(password) < MIN_PASSWORD_LENGTH:
            raise PasswordError(f"The password needs at least {MIN_PASSWORD_LENGTH} characters")
        salt = secrets.token_hex(16)
        self._store.put(PASSWORD_KEY, f"{salt}${self._hash(password, salt)}")

    def verify(self, password: str) -> bool:
        """True if the password matches the stored hash; False when none is set."""
        stored = self._store.get(PASSWORD_KEY)
        if stored is None:
            return False
        salt, expected = stored.split("$", 1)
        return hmac.compare_digest(self._hash(password, salt), expected)

    def session_secret(self) -> str:
        """The secret that signs session cookies, generated and stored on first use."""
        secret = self._store.get(SECRET_KEY)
        if secret is None:
            secret = secrets.token_urlsafe(32)
            self._store.put(SECRET_KEY, secret)
        return secret

    @staticmethod
    def _hash(password: str, salt: str) -> str:
        return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **SCRYPT).hex()
