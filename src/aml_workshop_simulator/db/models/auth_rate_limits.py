from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, JSONVariant, TZDateTime


class AuthRateLimit(Base):
    __tablename__ = 'auth_rate_limits'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[dict] = mapped_column(JSONVariant)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, index=True)
