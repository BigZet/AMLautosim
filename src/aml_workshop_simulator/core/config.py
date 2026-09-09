from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    PostgreSQL is the only supported persistent store; the default URL points at
    a local PostgreSQL instance; Docker Compose overrides it with `db`.
    """

    PROJECT_NAME: str = "AML Workshop Simulator"
    API_V1_STR: str = "/api/v1"

    SESSION_TTL_MINUTES: int = 240
    LOGIN_MAX_FAILED_ATTEMPTS: int = 10
    LOGIN_LOCKOUT_MINUTES: int = 5

    DATABASE_URL: str = "postgresql+asyncpg://aml:aml@localhost:5432/aml_simulator"
    ECHO_SQL: bool = False
    DB_POOL_DISABLED: bool = False

    BOOTSTRAP_ADMIN_EMAIL: str = "admin@example.com"
    BOOTSTRAP_ADMIN_PASSWORD: str = "admin12345"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
