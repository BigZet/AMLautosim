from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    PostgreSQL is the only supported persistent store; the default URL points at
    the `db` service from `docker-compose.yml`.
    """

    PROJECT_NAME: str = "AML Workshop Simulator"
    API_V1_STR: str = "/api/v1"

    SECRET_KEY: str = "change-me-for-production"
    SESSION_TTL_MINUTES: int = 240
    LOGIN_MAX_FAILED_ATTEMPTS: int = 10
    LOGIN_LOCKOUT_MINUTES: int = 5
    SESSION_LAST_SEEN_THROTTLE_SECONDS: int = 300

    DATABASE_URL: str = "postgresql+asyncpg://aml:aml@localhost:5432/aml_simulator"
    ECHO_SQL: bool = False
    DB_POOL_DISABLED: bool = False

    COOKIE_SECURE: bool = False

    #: Comma separated addresses/CIDRs of reverse proxies whose
    #: `X-Forwarded-For` header may be believed. Empty means: trust nothing
    #: but the socket peer.
    TRUSTED_PROXY_IPS: str = ""

    BOOTSTRAP_ADMIN_EMAIL: str = "admin@example.com"
    BOOTSTRAP_ADMIN_PASSWORD: str = "admin12345"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def sync_database_url(self) -> str:
        """Synchronous DSN for tooling that cannot use asyncpg."""
        return self.DATABASE_URL.replace("+asyncpg", "+psycopg2").replace(
            "+aiosqlite", ""
        )


settings = Settings()
