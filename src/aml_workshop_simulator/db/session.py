from __future__ import annotations

from collections.abc import AsyncGenerator
import time

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.observability import metrics

# Tests create a fresh event loop per case; a pooled connection must never be
# reused across loops, so pooling can be disabled explicitly.
_engine_kwargs: dict[str, object] = {
    "echo": settings.ECHO_SQL,
    # A pooled connection can outlive a database restart.
    "pool_pre_ping": True,
}
if settings.DB_POOL_DISABLED:
    _engine_kwargs["poolclass"] = NullPool

async_engine = create_async_engine(settings.database_url, **_engine_kwargs)


@event.listens_for(async_engine.sync_engine, 'before_cursor_execute')
def _sql_start(conn, cursor, statement, parameters, context, executemany):
    context._aml_started = time.monotonic()


@event.listens_for(async_engine.sync_engine, 'after_cursor_execute')
def _sql_done(conn, cursor, statement, parameters, context, executemany):
    metrics.observe('sql_seconds', time.monotonic() - context._aml_started)


@event.listens_for(async_engine.sync_engine, 'handle_error')
def _sql_error(context):
    metrics.add('sql_errors', 1)
    started = getattr(context.execution_context, '_aml_started', None)
    if started is not None:
        metrics.observe('sql_seconds', time.monotonic() - started)


def pool_metrics():
    pool = async_engine.sync_engine.pool
    return {'pool_checked_out': pool.checkedout() if hasattr(pool, 'checkedout') else 0,
            'pool_overflow': max(0, pool.overflow()) if hasattr(pool, 'overflow') else 0}


class MeasuredSession(AsyncSession):
    async def execute(self, *args, **kwargs):
        started = time.monotonic()
        try:
            await self.connection()
        finally:
            metrics.observe('pool_acquire_seconds', time.monotonic() - started)
            for key, value in pool_metrics().items():
                metrics.gauge(key, value)
        return await super().execute(*args, **kwargs)


AsyncSessionLocal = async_sessionmaker(async_engine, class_=MeasuredSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
