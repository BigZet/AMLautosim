"""What the participant's *browser* said, forwarded to the API.

Streamlit is an HTTP client in its own right: the API sees the UI process, not
the person using it. Without this module every row in `sessions` would record
`python-httpx/...` and the address of the Streamlit container, which makes the
technical information in the admin panel worthless.

Nothing here is trusted on its own:

* the user agent and the language are the browser's own claims, exactly as they
  would be on a request that reached the API directly;
* the address travels as `X-Forwarded-For`, and `core.request_meta` believes it
  only when the caller is listed in `TRUSTED_PROXY_IPS`. An unconfigured
  deployment therefore keeps recording the socket address instead of anything a
  client could dictate.

No cookies, no fingerprinting surface, nothing beyond the three values the
admin panel actually shows.
"""

from __future__ import annotations

from ipaddress import ip_address

import streamlit as st

#: Long headers are truncated to the width the database columns can hold; the
#: API truncates again to the same limits before storing anything.
MAX_USER_AGENT = 512
MAX_LANGUAGE = 120


def _headers() -> dict[str, str]:
    """The browser headers of the current script run, or nothing."""
    try:
        raw = st.context.headers
    except Exception:  # pragma: no cover - no script context (tests, imports)
        return {}
    if not raw:
        return {}
    try:
        return {str(key): str(value) for key, value in raw.items()}
    except Exception:  # pragma: no cover - defensive
        return {}


def _lookup(headers: dict[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted and value.strip():
            return value.strip()
    return None


def client_address() -> str | None:
    """The browser's address as Streamlit sees it, if it is a valid one."""
    try:
        raw = st.context.ip_address
    except Exception:  # pragma: no cover - older runtime or no script context
        return None
    if not raw:
        return None
    try:
        return str(ip_address(str(raw).strip()))
    except ValueError:
        return None


def browser_headers() -> dict[str, str]:
    """Headers to add to an API call so the session records the real client."""
    headers = _headers()
    forwarded: dict[str, str] = {}

    user_agent = _lookup(headers, "user-agent")
    if user_agent:
        forwarded["User-Agent"] = user_agent[:MAX_USER_AGENT]

    language = _lookup(headers, "accept-language")
    if language:
        forwarded["Accept-Language"] = language[:MAX_LANGUAGE]

    address = client_address()
    if address:
        forwarded["X-Forwarded-For"] = address

    return forwarded
