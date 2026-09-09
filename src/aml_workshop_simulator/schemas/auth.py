from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.aml_workshop_simulator.core.enums import UserRole

STRICT = ConfigDict(extra="forbid")

#: Documented password policy: 10..128 characters.
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128


class RegisterIn(BaseModel):
    model_config = STRICT

    email: EmailStr
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_display_name(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class UserRegisteredOut(BaseModel):
    id: int
    email: EmailStr
    display_name: str
    role: UserRole
    created_at: datetime


class LoginIn(BaseModel):
    model_config = STRICT

    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    audience: Literal["play", "admin"] = "play"


class UserInfo(BaseModel):
    id: int
    display_name: str
    role: UserRole


class SessionCreatedOut(BaseModel):
    session_id: str
    expires_at: datetime
    audience: Literal["play", "admin"]
    user: UserInfo


class UserSessionOut(BaseModel):
    id: int
    display_name: str
    role: UserRole
    audience: Literal["play", "admin"]
    is_blocked: bool = False
    access_revision: int = 1
