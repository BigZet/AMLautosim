from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Security, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import (
    CurrentPrincipal,
    get_principal,
    session_header,
)
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.schemas.auth import (
    LoginIn,
    RegisterIn,
    SessionCreatedOut,
    UserRegisteredOut,
    UserSessionOut,
)
from src.aml_workshop_simulator.services import authentication as operations

router = APIRouter()


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
    return await operations.register(payload=payload, db=db)


@router.post("/login", response_model=SessionCreatedOut, operation_id="auth_login")
async def login(
    payload: LoginIn,
    db: AsyncSession = Depends(get_db),
) -> SessionCreatedOut:
    return await operations.login(payload=payload, db=db)


@router.get("/session", response_model=UserSessionOut, operation_id="auth_session")
async def read_session(
    principal: CurrentPrincipal = Depends(get_principal),
) -> UserSessionOut:
    return await operations.read_session(principal=principal)


@router.delete(
    "/session",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="auth_logout",
)
async def logout(
    x_session_id: Annotated[str | None, Security(session_header)] = None,
    db: AsyncSession = Depends(get_db),
) -> None:
    return await operations.logout(x_session_id=x_session_id, db=db)
