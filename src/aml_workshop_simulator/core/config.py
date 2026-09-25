from __future__ import annotations

from pathlib import Path
from ipaddress import ip_network
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


class Settings(BaseSettings):
    """Runtime configuration.

    PostgreSQL is the only supported persistent store; the default URL points at
    a local PostgreSQL instance; Docker Compose overrides it with `db`.
    """

    PROJECT_NAME: str = "AML Workshop Simulator"
    GIT_SHA: str = Field(default="development", pattern=r"^(development|[0-9a-f]{40})$")
    IMAGE_REFERENCE: str = "local"
    METRICS_TOKEN: SecretStr | None = None
    API_V1_STR: str = "/api/v1"

    EXPANDED_ROUNDS_ENABLED: bool = True

    SESSION_TTL_MINUTES: int = Field(default=240, gt=0)
    LOGIN_MAX_FAILED_ATTEMPTS: int = Field(default=10, gt=0)
    LOGIN_LOCKOUT_MINUTES: int = Field(default=5, gt=0)
    AUTH_PAIR_PER_MINUTE: int = Field(default=10, gt=0)
    AUTH_IP_PER_MINUTE: int = Field(default=300, gt=0)
    AUTH_IP_BURST: int = Field(default=120, gt=0)
    AUTH_CONTEXT_SECRET: SecretStr | None = None
    AUTH_TRUSTED_UI_CIDRS: list[str] = []

    @field_validator("AUTH_TRUSTED_UI_CIDRS")
    @classmethod
    def validate_networks(cls, value):
        return [str(ip_network(network)) for network in value]

    # Explicit URL takes precedence for local tooling and disposable test DBs.
    DATABASE_URL: str | None = None
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "aml_simulator"
    POSTGRES_USER: str = "aml"
    POSTGRES_PASSWORD: str = ""
    ECHO_SQL: bool = False
    DB_POOL_DISABLED: bool = False
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=100)
    DB_POOL_OVERFLOW: int = Field(default=10, ge=0, le=100)
    DB_POOL_TIMEOUT: float = Field(default=5, gt=0, le=120)
    DB_POOL_RECYCLE: int = Field(default=1800, ge=1, le=86400)
    API_WORKERS: int = Field(default=1, ge=1, le=4)
    PASSWORD_ARGON2_ENABLED: bool = True
    SCORING_THREADS: int = Field(default=2, ge=1, le=4)
    SCORING_LEASE_SECONDS: int = Field(default=30, ge=5, le=3600)
    SCORING_MAX_SCENARIOS: int = Field(default=1000, ge=1, le=10000)
    SCORING_MAX_SNAPSHOT_BYTES: int = Field(default=64 * 1024 * 1024, ge=1048576, le=536870912)

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

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")


settings = Settings()
