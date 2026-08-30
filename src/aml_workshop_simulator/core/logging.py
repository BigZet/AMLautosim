"""Structured JSON logging, as `docs/operations.md` §7 specifies it.

One JSON object per line. An operator finds an incident by `request_id` and gets
the whole chain: the request that started it, the domain event it caused and the
response that went back — §8 of the same document.

The field allowlist lives here rather than at the call sites. A log call is the
one place where a value that must never leave the service can leave it by
accident, and the call sites are spread across every router; `docs/security.md`
§3 asks for allowlist logging for exactly that reason. Anything not named below
is dropped and only its *name* is reported, under `dropped_fields`.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

#: Correlation id of the request being served, set by the API middleware.
REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)

#: Everything a log line may carry. §7 lists the mandatory fields; the rest are
#: internal identifiers and small enumerations that carry no personal data.
#: Deliberately absent, per §7: email, display name, password or its hash, raw
#: session id, cookie, session hash, `X-Session-ID`, request body, full
#: scenario, action details, explanation, DSN and raw idempotency key.
ALLOWED_FIELDS = frozenset(
    {
        "audience",
        "blocked",
        "config_version",
        "count",
        "duration_ms",
        "error_type",
        "event",
        "latency_ms",
        "method",
        "outcome",
        "reason_code",
        "revision",
        "role",
        "round_id",
        "round_status",
        "route",
        "scenario_id",
        "scenario_status",
        "status_code",
        "target_user_id",
        "user_id",
        "version_id",
    }
)

LOGGER_NAME = "aml"
_logger = logging.getLogger(LOGGER_NAME)


class JsonFormatter(logging.Formatter):
    """Render one record as the object documented in §7."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _timestamp(record.created),
            "level": record.levelname,
            "service": self.service,
            "event": getattr(record, "event", record.getMessage()),
            "request_id": getattr(record, "request_id", None),
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            # The traceback is the whole point of logging a 500; without it the
            # error envelope is all anyone ever sees.
            payload["error_type"] = record.exc_info[0].__name__
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(service: str, level: int = logging.INFO) -> None:
    """Send `aml` records to stdout as JSON. Safe to call more than once."""
    _logger.setLevel(level)
    _logger.propagate = False
    # `logging.config.fileConfig` (Alembic) disables existing loggers by
    # default; configuring ours is an explicit statement that it is wanted.
    _logger.disabled = False
    for handler in list(_logger.handlers):
        _logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    _logger.addHandler(handler)


def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Emit one structured event, dropping anything outside the allowlist."""
    _logger.log(level, event, extra=_extra(event, fields))


def log_exception(event: str, **fields: Any) -> None:
    """Emit one structured event carrying the exception being handled."""
    _logger.error(event, exc_info=True, extra=_extra(event, fields))


def _extra(event: str, fields: dict[str, Any]) -> dict[str, Any]:
    kept = {key: value for key, value in fields.items() if key in ALLOWED_FIELDS}
    rejected = sorted(set(fields) - ALLOWED_FIELDS)
    if rejected:
        # Names are safe to report; the values are what the allowlist protects.
        kept["dropped_fields"] = rejected
    return {"event": event, "request_id": REQUEST_ID.get(), "fields": kept}


def _timestamp(created: float) -> str:
    moment = datetime.fromtimestamp(created, UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")
