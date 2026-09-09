"""Single error envelope for every API failure.

```json
{"code": "...", "message": "...", "details": {...}, "request_id": "..."}
```

`message` is the text a participant or administrator can act on; `code` and
`details` are the stable contract the Streamlit client branches on.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any


class ApplicationError(Exception):
    """Application error rendered as the shared envelope."""

    status_code: int = HTTPStatus.BAD_REQUEST
    code: str = "error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details
        self.headers = headers


class ValidationFailed(ApplicationError):
    """Schema / card-contract failure. Never modifies stored state."""

    status_code = 422
    code = "validation_error"


class ScenarioValidationFailed(ApplicationError):
    """Structurally valid chain that breaks the round's business rules."""

    status_code = HTTPStatus.BAD_REQUEST
    code = "scenario_validation_failed"


class NotAuthenticated(ApplicationError):
    status_code = HTTPStatus.UNAUTHORIZED
    code = "session_missing"


class Forbidden(ApplicationError):
    status_code = HTTPStatus.FORBIDDEN
    code = "forbidden"


class AccountBlocked(ApplicationError):
    status_code = HTTPStatus.FORBIDDEN
    code = "account_blocked"


class NotFound(ApplicationError):
    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"


class Conflict(ApplicationError):
    status_code = HTTPStatus.CONFLICT
    code = "conflict"


class RateLimited(ApplicationError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limited"
