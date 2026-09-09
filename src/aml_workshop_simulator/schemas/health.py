"""Liveness and readiness response contracts."""

from typing import Literal

from pydantic import BaseModel


class LiveOut(BaseModel):
    status: Literal["ok"]
    service: Literal["api"]
    version: str


class ReadinessChecks(BaseModel):
    database: Literal["connected", "unavailable"]
    ruleset_versions: list[str] | None = None
    migrations: Literal["head", "behind head", "alembic_version missing"] | None = None


class ReadyOut(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: ReadinessChecks
