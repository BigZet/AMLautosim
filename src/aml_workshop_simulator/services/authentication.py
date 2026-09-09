"""Application operations for authentication."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.errors import (
    AccountBlocked,
    Conflict,
    Forbidden,
    NotAuthenticated,
    RateLimited,
)
from src.aml_workshop_simulator.core.principal import (
    CurrentPrincipal,
)
from src.aml_workshop_simulator.core.security import (
    get_password_hash,
    hash_session_id,
    new_session_id,
    verify_password,
)
from src.aml_workshop_simulator.db.models.sessions import Session
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.schemas.auth import (
    LoginIn,
    RegisterIn,
    SessionCreatedOut,
    UserInfo,
    UserRegisteredOut,
    UserSessionOut,
)

INVALID_CREDENTIALS = "Неверный email или пароль."
# Always verify a hash, including for an unknown account.
DUMMY_PASSWORD_HASH = get_password_hash("unused-dummy-password")


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def register(*, payload: RegisterIn, db: AsyncSession) -> UserRegisteredOut:
    email = normalize_email(str(payload.email))
    now = datetime.now(UTC)
    user = User(
        email=email,
        display_name=payload.display_name.strip(),
        hashed_password=await asyncio.to_thread(get_password_hash, payload.password),
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
    # refresh() подтягивает значения, выставленные самой БД (например,
    # автоинкрементный id), которых не было в объекте до commit().
    await db.refresh(user)
    return UserRegisteredOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name or "",
        role=user.role,
        created_at=user.created_at,
    )


async def login(*, payload: LoginIn, db: AsyncSession) -> SessionCreatedOut:
    email = normalize_email(str(payload.email))
    user = (
        (await db.execute(select(User).where(User.email == email).with_for_update()))
        .scalars()
        .first()
    )
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

    verified = await asyncio.to_thread(
        verify_password,
        payload.password,
        user.hashed_password if user else DUMMY_PASSWORD_HASH,
    )
    if user is None or not verified:
        if user is not None:
            user.failed_login_count = int(user.failed_login_count or 0) + 1
            if user.failed_login_count >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
                user.locked_until = now + timedelta(
                    minutes=settings.LOGIN_LOCKOUT_MINUTES
                )
                user.failed_login_count = 0
            # commit только неудачной попытки — сессия при этом не создаётся.
            await db.commit()
        raise NotAuthenticated(INVALID_CREDENTIALS, code="invalid_credentials")

    if user.is_blocked:
        # Ручная блокировка администратором — отдельный от lockout механизм:
        # lockout временный и снимается сам по истечении времени, is_blocked
        # держится, пока администратор явно не снимет блокировку.
        raise AccountBlocked(
            "Доступ к учетной записи заблокирован организатором.",
            code="account_blocked",
        )

    if payload.audience == "admin" and user.role != "admin":
        raise Forbidden(
            "Недостаточно прав для административного входа.", code="forbidden"
        )
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
        )
    )
    # Успешный вход полностью сбрасывает историю неудачных попыток и любую
    # временную блокировку — иначе пользователь мог бы залогиниться, а через
    # секунду словить lockout из-за старого счётчика.
    user.failed_login_count = 0
    user.locked_until = None
    if user.first_login_at is None:
        user.first_login_at = now
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


async def read_session(*, principal: CurrentPrincipal) -> UserSessionOut:
    user = principal.user
    return UserSessionOut(
        id=user.id,
        display_name=user.display_name or user.email,
        role=user.role,
        audience=principal.audience,
        is_blocked=bool(user.is_blocked),
        access_revision=int(user.access_revision or 1),
    )


async def logout(*, x_session_id: str | None, db: AsyncSession) -> None:
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


async def resolve_principal(
    raw_session_id: str | None,
    db: AsyncSession,
) -> CurrentPrincipal | None:
    if not raw_session_id:
        return None

    digest = hash_session_id(raw_session_id.strip())
    row = (
        await db.execute(
            select(Session, User)
            .join(User, Session.user_id == User.id)
            .where(Session.session_id_hash == digest)
        )
    ).first()
    if row is None:
        raise NotAuthenticated(
            "Сессия недействительна. Выполните вход заново.", code="session_invalid"
        )

    session_row, user = row
    now = datetime.now(UTC)
    if session_row.revoked_at is not None:
        raise NotAuthenticated(
            "Сессия завершена. Выполните вход заново.", code="session_revoked"
        )
    expires_at = session_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        raise NotAuthenticated(
            "Срок сессии истек. Выполните вход заново.", code="session_expired"
        )
    if user.is_blocked:
        raise AccountBlocked(
            "Доступ к учетной записи заблокирован организатором.",
            code="account_blocked",
        )

    return CurrentPrincipal(user=user, audience=str(session_row.audience))
