"""Opaque cursors for the paginated endpoints.

A cursor carries the sort key of the last row a caller received, base64url
encoded so nothing outside this module can depend on its shape. Keyset paging is
used wherever the rows come from a query: it stays correct while participants
register and events accumulate, which offsets do not — an offset page silently
repeats or skips rows as soon as anything is inserted before it.

The two leaderboards are built whole in Python from a completed round, so their
"cursor" is a position in an already-frozen ranking; `generated_at` in the
response is what tells the caller which ranking it belongs to.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from aml_workshop_simulator.api.errors import ValidationFailed

T = TypeVar("T")


def encode_cursor(values: Sequence[Any]) -> str:
    """Pack one row's sort key into the token handed back as `next_cursor`."""
    payload = json.dumps(list(values), separators=(",", ":"), default=str)
    return (
        base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    )


def decode_cursor(cursor: str | None, arity: int) -> list[Any] | None:
    """Unpack a cursor, or `None` when the caller asked for the first page.

    A malformed cursor is the caller's error, not a reason to serve page one:
    silently restarting would make a paging loop repeat forever.
    """
    if not cursor:
        return None
    padding = "=" * (-len(cursor) % 4)
    try:
        payload = base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        values = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as error:
        raise _malformed() from error
    if not isinstance(values, list) or len(values) != arity:
        raise _malformed()
    return values


def take_page(
    rows: Sequence[T], limit: int, key: Callable[[T], Sequence[Any]]
) -> tuple[list[T], str | None]:
    """Split a deliberate `limit + 1` fetch into a page and the cursor after it.

    Fetching one extra row is what makes `next_cursor` honest: the endpoint knows
    there is a further page instead of guessing from a full page.
    """
    page = list(rows[:limit])
    if len(rows) <= limit:
        return page, None
    return page, encode_cursor(key(page[-1]))


def _malformed() -> ValidationFailed:
    return ValidationFailed(
        "Курсор постраничности поврежден. Откройте список заново.",
        code="invalid_cursor",
    )
