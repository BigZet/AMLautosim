from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.aml_workshop_simulator.core.config import settings

# Tests create a fresh event loop per case; a pooled connection must never be
# reused across loops, so pooling can be disabled explicitly.
_engine_kwargs: dict[str, object] = {
    "echo": settings.ECHO_SQL,
    # A pooled connection can outlive a database restart.
    "pool_pre_ping": True,
}
if settings.DB_POOL_DISABLED:
    _engine_kwargs["poolclass"] = NullPool

async_engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
