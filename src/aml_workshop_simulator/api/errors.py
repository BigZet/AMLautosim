"""Single error envelope for every API failure.

```json
{"code": "...", "message": "...", "details": {...}, "request_id": "..."}
```

`message` is the text a participant or administrator can act on; `code` and
`details` are the stable contract the Streamlit client branches on.
"""

from __future__ import annotations

from typing import Any

from fastapi import status


class ApiError(Exception):
    """Application error rendered as the shared envelope."""

    status_code: int = status.HTTP_400_BAD_REQUEST
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

    def envelope(self, request_id: str | None) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "request_id": request_id,
        }


class ValidationFailed(ApiError):
    """Schema / card-contract failure. Never modifies stored state."""

    status_code = 422
    code = "validation_error"


class ScenarioValidationFailed(ApiError):
    """Structurally valid chain that breaks the round's business rules."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "scenario_validation_failed"


class NotAuthenticated(ApiError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "session_missing"


class Forbidden(ApiError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class AccountBlocked(ApiError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "account_blocked"


class NotFound(ApiError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class Conflict(ApiError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class RateLimited(ApiError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class ServiceUnavailable(ApiError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"


def violations_payload(violations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"violations": violations}


def first_message(violations: list[dict[str, Any]], fallback: str) -> str:
    for violation in violations:
        message = violation.get("message")
        if message:
            return str(message)
    return fallback
