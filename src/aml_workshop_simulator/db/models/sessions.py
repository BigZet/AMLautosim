import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BigIntVariant, TZDateTime

# INET on PostgreSQL (IPv4 and IPv6), plain text elsewhere.
IPAddress = String(45).with_variant(INET(), 'postgresql')


class Session(Base):
    __tablename__ = 'sessions'
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(
        BigIntVariant, ForeignKey(
            'users.id', ondelete='CASCADE'))
    session_id_hash: Mapped[str] = mapped_column(String(64), unique=True)
    audience: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(TZDateTime)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(TZDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    revoke_reason: Mapped[str | None] = mapped_column(String(100))
    rotated_from_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey('sessions.id'))
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        BigIntVariant, ForeignKey('users.id', ondelete='SET NULL'))
    # Technical login metadata, visible to administrators only.
    ip_address: Mapped[str | None] = mapped_column(IPAddress)
    user_agent: Mapped[str | None] = mapped_column(String(512))
    accept_language: Mapped[str | None] = mapped_column(String(120))
