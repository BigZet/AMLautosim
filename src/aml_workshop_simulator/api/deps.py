"""Authentication and authorisation dependencies.

The raw session identifier never travels past this module: routers receive a
`CurrentPrincipal` describing who is calling and with which audience.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.errors import AccountBlocked, Forbidden, NotAuthenticated
from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.security import hash_session_id
from src.aml_workshop_simulator.db.models.sessions import Session
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.session import get_db

SESSION_HEADER = "X-Session-ID"


@dataclass(frozen=True)
class CurrentPrincipal:
    user: User
    session_row_id: object
    audience: str

    @property
    def user_id(self) -> int:
        return int(self.user.id)

    @property
    def role(self) -> str:
        return str(self.user.role)


async def _resolve_principal(
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
        raise NotAuthenticated("Сессия недействительна. Выполните вход заново.", code="session_invalid")

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
            "Доступ к учетной записи заблокирован организатором.", code="account_blocked"
        )

    last_seen = session_row.last_seen_at
    if last_seen is not None and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    throttle = timedelta(seconds=settings.SESSION_LAST_SEEN_THROTTLE_SECONDS)
    if last_seen is None or now - last_seen >= throttle:
        session_row.last_seen_at = now
        await db.commit()

    return CurrentPrincipal(
        user=user, session_row_id=session_row.id, audience=str(session_row.audience)
    )


async def get_principal_optional(
    x_session_id: Annotated[str | None, Header(alias=SESSION_HEADER)] = None,
    db: AsyncSession = Depends(get_db),
) -> CurrentPrincipal | None:
    if not x_session_id:
        return None
    return await _resolve_principal(x_session_id, db)


async def get_principal(
    x_session_id: Annotated[str | None, Header(alias=SESSION_HEADER)] = None,
    db: AsyncSession = Depends(get_db),
) -> CurrentPrincipal:
    if not x_session_id:
        raise NotAuthenticated(
            "Требуется вход в систему.", code="session_missing"
        )
    principal = await _resolve_principal(x_session_id, db)
    if principal is None:
        raise NotAuthenticated("Сессия недействительна.", code="session_invalid")
    return principal


async def get_current_participant(
    principal: CurrentPrincipal = Depends(get_principal),
) -> CurrentPrincipal:
    if principal.audience != "play":
        raise Forbidden(
            "Эта сессия не предназначена для игрового интерфейса.", code="forbidden"
        )
    return principal


async def get_current_admin(
    principal: CurrentPrincipal = Depends(get_principal),
) -> CurrentPrincipal:
    if principal.role != "admin" or principal.audience != "admin":
        raise Forbidden(
            "Недостаточно прав: требуется административная сессия.", code="forbidden"
        )
    return principal
