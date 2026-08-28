from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.models.sessions import Session


def hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


async def get_current_user_optional(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    token = x_session_id
    if not token and authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:].strip()
        else:
            token = authorization.strip()

    if not token:
        return None

    # Check if session exists in DB by SHA-256 hash
    session_hash = hash_session_id(token)
    stmt = (
        select(Session, User)
        .join(User, Session.user_id == User.id)
        .where(
            Session.session_id_hash == session_hash,
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(timezone.utc),
        )
    )
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        return None

    session_obj, user = row
    if user.is_blocked:
        return None

    # Update last_seen_at
    session_obj.last_seen_at = datetime.now(timezone.utc)
    await db.commit()

    return user


async def get_current_user(
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="session_invalid_or_expired",
        )
    if user.is_blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account_blocked",
        )
    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="forbidden_admin_required",
        )
    return user
