from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Runtime configuration.

    PostgreSQL is the only supported persistent store; the default URL points at
    a local PostgreSQL instance; Docker Compose overrides it with `db`.
    """

    PROJECT_NAME: str = "AML Workshop Simulator"
    API_V1_STR: str = "/api/v1"

    EXPANDED_ROUNDS_ENABLED: bool = True

    SESSION_TTL_MINUTES: int = Field(default=240, gt=0)
    LOGIN_MAX_FAILED_ATTEMPTS: int = Field(default=10, gt=0)
    LOGIN_LOCKOUT_MINUTES: int = Field(default=5, gt=0)

    # Explicit URL takes precedence for local tooling and disposable test DBs.
    DATABASE_URL: str | None = None
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "aml_simulator"
    POSTGRES_USER: str = "aml"
    POSTGRES_PASSWORD: str = ""
    ECHO_SQL: bool = False
    DB_POOL_DISABLED: bool = False

    BOOTSTRAP_ADMIN_EMAIL: str = "admin@example.com"
    BOOTSTRAP_ADMIN_PASSWORD: str = ""

    @property
    def database_url(self) -> str | URL:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return URL.create(
            "postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
