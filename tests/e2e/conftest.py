"""Fixtures for the end-to-end suite.

The end-to-end tests drive the same live stack as the browser tests — one
PostgreSQL database, one FastAPI process and both Streamlit processes — so the
fixtures are imported from `tests.ui.conftest` instead of being duplicated.
Without this module the suite cannot resolve `stack`, `reset_state` or
`draft_state`: a `conftest.py` only serves its own directory tree.
"""

from __future__ import annotations

from tests.ui.conftest import (  # noqa: F401
    draft_state,
    reset_state,
    stack,
)
