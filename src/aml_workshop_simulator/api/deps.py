"""Authentication and authorisation dependencies.

The raw session identifier never travels past this module: routers receive a
`CurrentPrincipal` describing who is calling and with which audience.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.errors import (
    Forbidden,
    NotAuthenticated,
)
from src.aml_workshop_simulator.core.principal import CurrentPrincipal
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.services import authentication

SESSION_HEADER = "X-Session-ID"
session_header = APIKeyHeader(
    name=SESSION_HEADER, scheme_name="SessionId", auto_error=False
)


async def get_principal(
    x_session_id: Annotated[str | None, Security(session_header)] = None,
    db: AsyncSession = Depends(get_db),
) -> CurrentPrincipal:
    if not x_session_id:
        raise NotAuthenticated("Требуется вход в систему.", code="session_missing")
    principal = await authentication.resolve_principal(x_session_id, db)
    if principal is None:
        raise NotAuthenticated("Сессия недействительна.", code="session_invalid")
    return principal


async def get_current_participant(
    principal: CurrentPrincipal = Depends(get_principal),
) -> CurrentPrincipal:
    if principal.audience != "play" or principal.role != "participant":
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
