"""Password hashing and opaque session identifiers.

No JWT is issued: authentication state lives entirely in the `sessions` table.
Only `SHA-256(session_id)` is persisted, never the raw identifier.
"""

from __future__ import annotations

import hashlib
import secrets

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SESSION_ID_BYTES = 32


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except ValueError:
        return False


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def new_session_id() -> str:
    """32 CSPRNG bytes, base64url without padding."""
    return secrets.token_urlsafe(SESSION_ID_BYTES)


def hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def hash_idempotency_key(key: str) -> str:
    """Irreversible digest stored in audit events; the raw key is never kept."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
