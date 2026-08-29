from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

STRICT = ConfigDict(extra="forbid")

#: Documented password policy: 10..128 characters.
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128


class RegisterIn(BaseModel):
    model_config = STRICT

    email: EmailStr
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class UserRegisteredOut(BaseModel):
    id: int
    email: EmailStr
    display_name: str
    role: str
    created_at: datetime


class LoginIn(BaseModel):
    model_config = STRICT

    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    audience: Literal["play", "admin"] = "play"


class UserInfo(BaseModel):
    id: int
    display_name: str
    role: str


class SessionCreatedOut(BaseModel):
    session_id: str
    expires_at: datetime
    audience: str
    user: UserInfo


class UserSessionOut(BaseModel):
    id: int
    display_name: str
    role: str
    audience: str
    is_blocked: bool = False
    access_revision: int = 1
