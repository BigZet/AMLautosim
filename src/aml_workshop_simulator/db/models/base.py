from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import JSON

# JSON type that falls back to SQLite JSON but uses JSONB on Postgres
JSONVariant = JSON().with_variant(JSONB(), "postgresql")
TZDateTime = DateTime(timezone=True)
# BigInt on Postgres, Integer (with autoincrement support) on SQLite
BigIntVariant = Integer().with_variant(BigInteger(), "postgresql")


class Base(DeclarativeBase):
    pass
