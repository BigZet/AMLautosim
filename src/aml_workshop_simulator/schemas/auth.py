from __future__ import annotations

from typing import Literal, Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=4, max_length=128)


class UserRegisteredOut(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str
    audience: Literal["play", "admin"] = "play"


class UserInfo(BaseModel):
    id: int
    display_name: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class SessionCreatedOut(BaseModel):
    session_id: str
    expires_at: datetime
    audience: str
    user: UserInfo


class UserSessionOut(BaseModel):
    id: int
    display_name: str
    email: Optional[str] = None
    role: str
    is_blocked: bool = False
    access_revision: int = 1

    model_config = ConfigDict(from_attributes=True)
