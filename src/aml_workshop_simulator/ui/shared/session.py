"""Browser session bootstrap for both Streamlit apps.

The cookie stores nothing but an opaque session id; identity, role and expiry
live in PostgreSQL. A first render where the component has not answered yet is
a *pending* state, never a confirmed logout.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import streamlit as st
from streamlit_cookies_controller import CookieController

from src.aml_workshop_simulator.ui.shared.api_client import (
    APIClientError,
    SimulatorAPIClient,
)

PLAY_COOKIE = "aml_play_session_id"
ADMIN_COOKIE = "aml_admin_session_id"

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes"}
COOKIE_PATH = os.getenv("COOKIE_PATH", "/")

SESSION_ERROR_CODES = {
    "session_missing",
    "session_invalid",
    "session_expired",
    "session_revoked",
}


@dataclass
class UiSession:
    session_id: str | None
    user: dict[str, Any] | None
    pending: bool

    @property
    def authenticated(self) -> bool:
        return bool(self.session_id and self.user)


@st.cache_resource
def get_api_client() -> SimulatorAPIClient:
    """Only the HTTP connection pool is cached - never a session id."""
    return SimulatorAPIClient()


def get_cookie_controller(key: str) -> CookieController:
    """A fresh controller per script run.

    The controller reads `st.session_state[key]`, which Streamlit refreshes with
    the component's answer. Caching the instance would freeze the empty first
    reading and make every reload look like a logout.
    """
    return CookieController(key=key)


#: Cookie writes are deferred to the top of the next script run: the component
#: only reaches the browser when the script finishes, and `st.rerun()` right
#: after a login would discard it.
COOKIE_COMMAND_KEY = "_pending_cookie_command"


def queue_cookie_set(session_id: str, expires_at: str | None) -> None:
    st.session_state[COOKIE_COMMAND_KEY] = ("set", session_id, expires_at)


def queue_cookie_clear() -> None:
    st.session_state[COOKIE_COMMAND_KEY] = ("clear", None, None)


def apply_pending_cookie_command(
    controller: CookieController, cookie_name: str
) -> None:
    """Execute a queued cookie write during a normal render pass."""
    command = st.session_state.pop(COOKIE_COMMAND_KEY, None)
    if not command:
        return
    action, session_id, expires_at = command
    if action == "set" and session_id:
        store_session(controller, cookie_name, session_id, expires_at)
    elif action == "clear":
        clear_session(controller, cookie_name)


def store_session(
    controller: CookieController,
    cookie_name: str,
    session_id: str,
    expires_at: str | None,
) -> None:
    expires: datetime | None = None
    if expires_at:
        try:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            expires = None
    controller.set(
        cookie_name,
        session_id,
        path=COOKIE_PATH,
        expires=expires,
        secure=COOKIE_SECURE,
        same_site="strict",
    )


def clear_session(controller: CookieController, cookie_name: str) -> None:
    try:
        if controller.get(cookie_name) is not None:
            controller.remove(
                cookie_name,
                path=COOKIE_PATH,
                secure=COOKIE_SECURE,
                same_site="strict",
            )
    except Exception:
        # A missing cookie is not an error: local state is cleared regardless.
        pass


def resolve_session(
    controller: CookieController,
    cookie_name: str,
    client: SimulatorAPIClient,
) -> UiSession:
    """Hydrate the UI session from `st.session_state`, falling back to the cookie."""
    session_id = st.session_state.get("session_id")
    user = st.session_state.get("user")
    if session_id and user:
        return UiSession(session_id, user, pending=False)

    cookie_value = controller.get(cookie_name)
    if cookie_value is None:
        # The component may not have answered yet on the very first render.
        if not st.session_state.get("_cookie_seen"):
            st.session_state["_cookie_seen"] = True
            return UiSession(None, None, pending=True)
        return UiSession(None, None, pending=False)

    st.session_state["_cookie_seen"] = True
    try:
        profile = client.get_session(cookie_value)
    except APIClientError as error:
        if error.code in SESSION_ERROR_CODES or error.status_code in (401, 403):
            clear_session(controller, cookie_name)
            reset_user_state()
            return UiSession(None, None, pending=False)
        raise

    st.session_state["session_id"] = cookie_value
    st.session_state["user"] = profile
    # Signals that this run switched from anonymous to authenticated, so the
    # caller can start a clean render pass instead of mixing both trees.
    st.session_state["_hydrated_from_cookie"] = True
    return UiSession(cookie_value, profile, pending=False)


def consume_hydration_flag() -> bool:
    return bool(st.session_state.pop("_hydrated_from_cookie", False))


def reset_user_state() -> None:
    """Drop every user-scoped value so two accounts can never mix."""
    for key in (
        "session_id",
        "user",
        "draft_steps",
        "server_scenario",
        "server_revision",
        "field_errors",
        "chain_violations",
        "flash",
        "editing_step_id",
        "pending_command",
        "last_saved_hash",
        "loaded_for",
        "preview_cache",
        "participants_page",
        "reveal_names",
        "selected_version",
        "auth_error",
        "registered_email",
    ):
        st.session_state.pop(key, None)
