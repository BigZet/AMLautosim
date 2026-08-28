from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    details: Optional[dict[str, Any]] = None
    request_id: Optional[str] = None
