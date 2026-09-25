"""Password hashing and opaque session identifiers.

No JWT is issued: authentication state lives entirely in the `sessions` table.
Only `SHA-256(session_id)` is persisted, never the raw identifier.
"""

from __future__ import annotations

import hashlib
import secrets
from threading import BoundedSemaphore

from passlib.context import CryptContext
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

from .config import settings

# SHA-256 prehash prevents bcrypt truncation for the 128-character password contract.
pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")
argon2 = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
# Bound memory to four 64 MiB hashes per process during a shared-NAT login burst.
_password_slots = BoundedSemaphore(4)

SESSION_ID_BYTES = 32


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        with _password_slots:
            if hashed_password.startswith("$argon2"):
                return argon2.verify(hashed_password, plain_password)
            if hashed_password.startswith("$bcrypt-sha256$"):
                return pwd_context.verify(plain_password, hashed_password)
            return False
    except (ValueError, InvalidHashError, VerificationError):
        return False


def get_password_hash(password: str) -> str:
    with _password_slots:
        return (
            argon2.hash(password)
            if settings.PASSWORD_ARGON2_ENABLED
            else pwd_context.hash(password)
        )


def password_needs_rehash(hashed_password: str) -> bool:
    if not settings.PASSWORD_ARGON2_ENABLED:
        return False
    return not hashed_password.startswith("$argon2id$") or argon2.check_needs_rehash(
        hashed_password
    )


def new_session_id() -> str:
    """32 CSPRNG bytes, base64url without padding."""
    return secrets.token_urlsafe(SESSION_ID_BYTES)


def hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()
