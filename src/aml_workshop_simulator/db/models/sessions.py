import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, BigIntVariant, TZDateTime


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
    revoked_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(100))
    rotated_from_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey('sessions.id'))
    revoked_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigIntVariant, ForeignKey('users.id', ondelete='SET NULL'))
