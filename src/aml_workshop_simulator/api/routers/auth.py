from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import (
    SESSION_HEADER,
    CurrentPrincipal,
    get_principal,
)
from src.aml_workshop_simulator.api.errors import (
    AccountBlocked,
    Conflict,
    Forbidden,
    NotAuthenticated,
    RateLimited,
)
from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.security import (
    get_password_hash,
    hash_session_id,
    new_session_id,
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

router = APIRouter()

INVALID_CREDENTIALS = "Неверный email или пароль."


def normalize_email(email: str) -> str:
    return email.strip().lower()


@router.post(
    "/register",
    response_model=UserRegisteredOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="auth_register",
)
async def register(
    payload: RegisterIn,
    db: AsyncSession = Depends(get_db),
) -> UserRegisteredOut:
    email = normalize_email(str(payload.email))
    now = datetime.now(UTC)
    user = User(
        email=email,
        display_name=payload.display_name.strip(),
        hashed_password=get_password_hash(payload.password),
        role="participant",
        is_blocked=False,
        access_revision=1,
        failed_login_count=0,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "Участник с таким email уже зарегистрирован.",
            code="email_already_registered",
        ) from exc
    await db.refresh(user)
    return UserRegisteredOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name or "",
        role=user.role,
        created_at=user.created_at,
    )


@router.post("/login", response_model=SessionCreatedOut, operation_id="auth_login")
async def login(
    payload: LoginIn,
    db: AsyncSession = Depends(get_db),
) -> SessionCreatedOut:
    email = normalize_email(str(payload.email))
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalars().first()
    now = datetime.now(UTC)

    if user is not None:
        locked_until = user.locked_until
        if locked_until is not None and locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=UTC)
        if locked_until is not None and locked_until > now:
            raise RateLimited(
                "Слишком много неудачных попыток входа. Повторите позже.",
                code="login_temporarily_locked",
                headers={"Retry-After": str(int((locked_until - now).total_seconds()))},
            )

    if user is None or not verify_password(payload.password, user.hashed_password):
        if user is not None:
            user.failed_login_count = int(user.failed_login_count or 0) + 1
            if user.failed_login_count >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
                user.failed_login_count = 0
            await db.commit()
        raise NotAuthenticated(INVALID_CREDENTIALS, code="invalid_credentials")

    if user.is_blocked:
        raise AccountBlocked(
            "Доступ к учетной записи заблокирован организатором.", code="account_blocked"
        )

    if payload.audience == "admin" and user.role != "admin":
        raise Forbidden("Недостаточно прав для административного входа.", code="forbidden")
    if payload.audience == "play" and user.role != "participant":
        raise Forbidden(
            "Административная учетная запись не участвует в игровом раунде.",
            code="forbidden",
        )

    raw_session_id = new_session_id()
    expires_at = now + timedelta(minutes=settings.SESSION_TTL_MINUTES)
    db.add(
        Session(
            user_id=user.id,
            session_id_hash=hash_session_id(raw_session_id),
            audience=payload.audience,
            created_at=now,
            expires_at=expires_at,
            last_seen_at=now,
        )
    )
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    await db.commit()

    return SessionCreatedOut(
        session_id=raw_session_id,
        expires_at=expires_at,
        audience=payload.audience,
        user=UserInfo(
            id=user.id,
            display_name=user.display_name or user.email,
            role=user.role,
        ),
    )


@router.get("/session", response_model=UserSessionOut, operation_id="auth_session")
async def read_session(
    principal: CurrentPrincipal = Depends(get_principal),
) -> UserSessionOut:
    user = principal.user
    return UserSessionOut(
        id=user.id,
        display_name=user.display_name or user.email,
        role=user.role,
        audience=principal.audience,
        is_blocked=bool(user.is_blocked),
        access_revision=int(user.access_revision or 1),
    )


@router.delete(
    "/session",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="auth_logout",
)
async def logout(
    response: Response,
    x_session_id: Annotated[str | None, Header(alias=SESSION_HEADER)] = None,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke only the current session; other browsers stay signed in."""
    if not x_session_id:
        raise NotAuthenticated("Требуется активная сессия.", code="session_missing")
    await db.execute(
        update(Session)
        .where(
            Session.session_id_hash == hash_session_id(x_session_id.strip()),
            Session.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC), revoke_reason="logout")
    )
    await db.commit()
