import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


@dataclass(frozen=True, slots=True)
class SessionSecrets:
    session_token: str
    session_token_hash: str
    csrf_token: str
    expires_at: datetime


class PasswordService:
    def __init__(self) -> None:
        self._hasher = PasswordHasher()

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify_password(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def new_session_secrets(lifetime_seconds: int) -> SessionSecrets:
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    return SessionSecrets(
        session_token=session_token,
        session_token_hash=hash_token(session_token),
        csrf_token=csrf_token,
        expires_at=datetime.now(UTC) + timedelta(seconds=lifetime_seconds),
    )


def constant_time_equal(left: str, right: str) -> bool:
    return secrets.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
