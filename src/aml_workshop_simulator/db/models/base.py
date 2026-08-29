from sqlalchemy import Integer, BigInteger, DateTime
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import JSON
from sqlalchemy.dialects.postgresql import JSONB

# JSON type that falls back to SQLite JSON but uses JSONB on Postgres
JSONVariant = JSON().with_variant(JSONB(), "postgresql")
TZDateTime = DateTime(timezone=True)
# BigInt on Postgres, Integer (with autoincrement support) on SQLite
BigIntVariant = Integer().with_variant(BigInteger(), "postgresql")


class Base(DeclarativeBase):
    pass
