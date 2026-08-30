import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

# This is a src layout, so the package is one directory below the checkout root.
# Done here rather than through `prepend_sys_path`, whose splitting rules differ
# between Alembic versions, and `alembic upgrade` is run as its own process by
# the container, the seed and the migration tests alike.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from alembic import context  # noqa: E402
from sqlalchemy import pool  # noqa: E402
from sqlalchemy.engine import Connection  # noqa: E402
from sqlalchemy.ext.asyncio import async_engine_from_config  # noqa: E402

import aml_workshop_simulator.db.models  # noqa: E402, F401
from aml_workshop_simulator.core.config import settings  # noqa: E402
from aml_workshop_simulator.db.models.base import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    # Without this flag `fileConfig` disables every logger that already
    # exists and is not named in alembic.ini — including the application's own.
    # Anything that migrates in-process and then logs (`seed_database --migrate`)
    # would go silent.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = settings.DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.DATABASE_URL
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
