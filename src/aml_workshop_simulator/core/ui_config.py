"""Validated UI process settings, independent of the launch directory."""

from pathlib import Path

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .config import PROJECT_ROOT, project_path


class UISettings(BaseSettings):
    API_URL: AnyHttpUrl = "http://127.0.0.1:8000"
    UI_HOST: str = Field(default="127.0.0.1", min_length=1)
    UI_PORT: int = Field(default=8080, ge=1, le=65535)
    NICEGUI_STORAGE_PATH: Path = PROJECT_ROOT / ".nicegui"
    NICEGUI_STORAGE_SECRET: str | None = None
    NICEGUI_SESSION_COOKIE: str = Field(default="aml_ui", pattern=r"^[A-Za-z0-9_-]+$")
    COOKIE_SECURE: bool = False

    @field_validator("NICEGUI_STORAGE_PATH", mode="before")
    @classmethod
    def resolve_storage(cls, value):
        return project_path(value)

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")
