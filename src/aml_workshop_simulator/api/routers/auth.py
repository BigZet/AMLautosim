from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.security import (
    get_password_hash,
    verify_password,
)
from src.aml_workshop_simulator.db.models.sessions import Session
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.schemas.auth import (
    LoginIn,
    RegisterIn,
    SessionCreatedOut,
    UserInfo,
    UserRegisteredOut,
    UserSessionOut,
)
from src.aml_workshop_simulator.api.deps import (
    get_current_user,
    hash_session_id,
)

router = APIRouter()


@router.post("/register", response_model=UserRegisteredOut,
             status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterIn,
    db: AsyncSession = Depends(get_db),
) -> UserRegisteredOut:
    normalized_email = payload.email.strip().lower()

    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == normalized_email))
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email_already_registered",
        )

    user = User(
        email=normalized_email,
        display_name=payload.display_name.strip(),
        hashed_password=get_password_hash(payload.password),
        role="participant",
        is_blocked=False,
        access_revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserRegisteredOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name or "",
        role=user.role,
        created_at=user.created_at,
    )


@router.post("/login", response_model=SessionCreatedOut)
async def login(
    payload: LoginIn,
    db: AsyncSession = Depends(get_db),
) -> SessionCreatedOut:
    normalized_email = payload.email.strip().lower()
    stmt = select(User).where(User.email == normalized_email)
    res = await db.execute(stmt)
    user = res.scalars().first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )

    if user.is_blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account_blocked",
        )

    if payload.audience == "admin" and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="forbidden_audience",
        )

    # Generate 32 bytes raw session token
    raw_session_id = secrets.token_urlsafe(32)
    session_hash = hash_session_id(raw_session_id)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    session_row = Session(
        user_id=user.id,
        session_id_hash=session_hash,
        audience=payload.audience,
        created_at=now,
        expires_at=expires,
        last_seen_at=now,
        revoked_at=None,
    )
    db.add(session_row)

    user.last_login_at = now
    await db.commit()

    return SessionCreatedOut(
        session_id=raw_session_id,
        expires_at=expires,
        audience=payload.audience,
        user=UserInfo(
            id=user.id,
            display_name=user.display_name or user.email,
            role=user.role,
        ),
    )


@router.get("/session", response_model=UserSessionOut)
async def get_session_info(
    current_user: User = Depends(get_current_user),
) -> UserSessionOut:
    return UserSessionOut(
        id=current_user.id,
        display_name=current_user.display_name or current_user.email,
        email=current_user.email,
        role=current_user.role,
        is_blocked=current_user.is_blocked,
        access_revision=current_user.access_revision,
    )


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> None:
    token = x_session_id
    if not token and authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:].strip()
        else:
            token = authorization.strip()

    if token:
        session_hash = hash_session_id(token)
        stmt = (
            update(Session)
            .where(Session.session_id_hash == session_hash)
            .values(
                revoked_at=datetime.now(timezone.utc),
                revoke_reason="logout",
            )
        )
        await db.execute(stmt)
        await db.commit()
