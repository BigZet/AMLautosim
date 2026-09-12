"""Audience-specific authentication, with no NiceGUI or backend imports."""

from collections.abc import MutableMapping
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from .client import SESSION_ERRORS, APIClient, APIError

Audience = Literal["play", "admin"]


class Identity(BaseModel):
    id: int
    display_name: str
    role: Literal["participant", "admin"]


class LoginResult(BaseModel):
    session_id: str = Field(repr=False)
    expires_at: str
    audience: Audience
    user: Identity


class SessionInfo(Identity):
    audience: Audience
    is_blocked: bool
    access_revision: int


class Registration(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=128, repr=False)


def auth_key(audience: Audience) -> str:
    return f"auth_{audience}"


def credential(storage: MutableMapping, audience: Audience) -> str | None:
    return (storage.get(auth_key(audience)) or {}).get("session_id")


def invalidate(storage: MutableMapping, audience: Audience) -> None:
    storage.pop(auth_key(audience), None)
    generation_key = f"auth_generation_{audience}"
    storage[generation_key] = storage.get(generation_key, 0) + 1
    # Pending commands from an old identity must never run for the next one.
    storage.pop(f"workspace_{audience}", None)


async def login(
    api: APIClient,
    storage: MutableMapping,
    audience: Audience,
    email: str,
    password: str,
) -> bool:
    generation_key = f"auth_generation_{audience}"
    generation = storage.get(generation_key, 0) + 1
    storage[generation_key] = generation
    result = LoginResult.model_validate(
        await api.request(
            "POST",
            "auth/login",
            body={
                "email": email.strip(),
                "password": password,
                "audience": audience,
            },
        )
    )
    expected_role = "participant" if audience == "play" else "admin"
    if result.audience != audience or result.user.role != expected_role:
        await api.request("DELETE", "auth/session", session_id=result.session_id)
        raise APIError(
            "Этот вход не подходит для выбранного интерфейса.",
            code="forbidden",
            status=403,
        )
    if storage.get(generation_key) != generation:
        await api.request("DELETE", "auth/session", session_id=result.session_id)
        return False
    storage.pop(f"workspace_{audience}", None)
    storage[auth_key(audience)] = result.model_dump()
    return True


async def verify(
    api: APIClient, storage: MutableMapping, audience: Audience
) -> SessionInfo | None:
    token = credential(storage, audience)
    if not token:
        return None
    try:
        result = SessionInfo.model_validate(
            await api.request("GET", "auth/session", session_id=token)
        )
        if result.audience != audience or result.role != (
            "participant" if audience == "play" else "admin"
        ):
            raise APIError(
                "Войдите с подходящей учётной записью.", code="forbidden", status=403
            )
    except APIError as exc:
        if credential(storage, audience) == token and (
            exc.code in SESSION_ERRORS | {"account_blocked", "forbidden"}
        ):
            invalidate(storage, audience)
        raise
    return result if credential(storage, audience) == token else None


async def logout(api: APIClient, storage: MutableMapping, audience: Audience) -> None:
    token = credential(storage, audience)
    invalidate(storage, audience)
    if token:
        await api.request("DELETE", "auth/session", session_id=token)
