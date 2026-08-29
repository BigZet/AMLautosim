"""Dark and light appearance for both Streamlit applications.

`.streamlit/config.toml` ships the dark palette as the *server* theme, so the
first paint of every page is already dark. Switching to light cannot go through
the server — that setting is global, and two participants must be able to make
opposite choices — so light mode is a per-browser CSS overlay: it rewrites the
same custom properties Streamlit itself exposes (`--background-color`,
`--secondary-background-color`, `--text-color`, `--primary-color`,
`--border-color`) plus `color-scheme`, which is what native controls,
scrollbars and focus rings follow.

The choice is stored in a cookie, so it survives navigation, a rerun and a
reload, and it is applied before anything else is rendered.
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st

THEME_COOKIE = "aml_theme"
DARK = "dark"
LIGHT = "light"
DEFAULT_THEME = DARK

STATE_KEY = "_aml_theme"
#: Mode resolved for the current script run; `current_theme()` prefers it so a
#: cookie that answered late is honoured immediately.
RUN_KEY = "_aml_theme_run"
PENDING_KEY = "_aml_theme_pending"
#: Set once the viewer has used the switch in this browser session. From then on
#: the session decides, because a cookie read can still return the previous
#: value for a moment after the component has written the new one.
CHOSEN_KEY = "_aml_theme_chosen"

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes"}
COOKIE_PATH = os.getenv("COOKIE_PATH", "/")

#: Both palettes, kept in sync with `.streamlit/config.toml`.
PALETTES: dict[str, dict[str, str]] = {
    DARK: {
        "primary": "#4CC7AB",
        "primary_contrast": "#0B1210",
        "background": "#101513",
        "secondary_background": "#18201D",
        "text": "#E8EFEC",
        "muted": "#9FB3AC",
        "border": "#33413C",
        "sidebar_background": "#0C110F",
        "table_header": "#202A26",
        "danger": "#FF8A7A",
        "ok": "#5FD3A6",
        "warn": "#F2C879",
        "scheme": "dark",
    },
    LIGHT: {
        "primary": "#0E7A67",
        "primary_contrast": "#FFFFFF",
        "background": "#F5F7F6",
        "secondary_background": "#FFFFFF",
        "text": "#192420",
        "muted": "#54635E",
        "border": "#DCE4E1",
        "sidebar_background": "#EEF3F1",
        "table_header": "#EAF1EE",
        "danger": "#B3261E",
        "ok": "#1E8449",
        "warn": "#8A6100",
        "scheme": "light",
    },
}


def _stylesheet(mode: str) -> str:
    palette = PALETTES.get(mode, PALETTES[DEFAULT_THEME])
    return f"""
<style id="aml-theme-{mode}">
:root, [data-testid="stAppViewContainer"], [data-testid="stHeader"],
[data-testid="stSidebar"], [data-testid="stSidebarContent"] {{
    --primary-color: {palette['primary']};
    --background-color: {palette['background']};
    --secondary-background-color: {palette['secondary_background']};
    --text-color: {palette['text']};
    --border-color: {palette['border']};
    --aml-line: {palette['border']};
    --aml-muted: color-mix(in srgb, {palette['text']} 62%, transparent);
    --aml-danger: {palette['danger']};
    --aml-ok: {palette['ok']};
    --aml-warn: {palette['warn']};
    --aml-table-header: {palette['table_header']};
    color-scheme: {palette['scheme']};
}}
html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {{
    background-color: {palette['background']};
    color: {palette['text']};
}}
[data-testid="stHeader"] {{ background-color: {palette['background']}; }}
[data-testid="stSidebar"], [data-testid="stSidebarContent"] {{
    background-color: {palette['sidebar_background']};
    color: {palette['text']};
}}
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] li,
[data-testid="stAppViewContainer"] label,
[data-testid="stAppViewContainer"] h1,
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3,
[data-testid="stAppViewContainer"] h4,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label {{ color: {palette['text']}; }}
[data-testid="stMetric"], [data-testid="stExpander"], [data-baseweb="tab-panel"] {{
    background-color: {palette['secondary_background']};
    border-color: {palette['border']};
}}
[data-testid="stMetricValue"], [data-testid="stMetricLabel"] {{ color: {palette['text']}; }}
input, textarea, select,
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="base-input"] {{
    background-color: {palette['secondary_background']} !important;
    color: {palette['text']} !important;
    border-color: {palette['border']} !important;
}}
[data-baseweb="popover"] li, [role="option"] {{
    background-color: {palette['secondary_background']};
    color: {palette['text']};
}}
[role="option"][aria-selected="true"], [role="option"]:hover {{
    background-color: color-mix(in srgb, {palette['primary']} 22%, {palette['secondary_background']});
}}
table.aml-table th, table.aml-board th {{
    background-color: {palette['table_header']};
    color: {palette['text']};
}}
table.aml-table td, table.aml-board td,
table.aml-table th, table.aml-board th {{ border-color: {palette['border']}; }}

/* Streamlit paints buttons from the *server* theme, which cannot differ per
   viewer, so every button variant is repainted here for the chosen mode. */
button[data-testid^="stBaseButton-secondary"],
button[data-testid^="stBaseButton-borderless"],
button[data-testid^="stBaseButton-tertiary"],
button[data-testid^="stBaseButton-pills"],
button[data-testid^="stBaseButton-segmented"] {{
    background-color: {palette['secondary_background']} !important;
    color: {palette['text']} !important;
    border-color: {palette['border']} !important;
}}
button[data-testid^="stBaseButton-secondary"]:hover,
button[data-testid^="stBaseButton-borderless"]:hover {{
    border-color: {palette['primary']} !important;
    color: {palette['primary']} !important;
}}
button[data-testid^="stBaseButton-primary"] {{
    background-color: {palette['primary']} !important;
    color: {palette['primary_contrast']} !important;
    border-color: {palette['primary']} !important;
}}
button[data-testid^="stBaseButton-primary"]:disabled,
button[data-testid^="stBaseButton-secondary"]:disabled {{
    opacity: .45;
}}
[data-testid="stHeader"] button, [data-testid="stMainMenuButton"],
[data-testid="stSidebarCollapseButton"] button {{ color: {palette['text']} !important; }}
[data-baseweb="input"] button, [data-testid="stTextInput"] button {{
    color: {palette['muted']} !important;
    background: transparent !important;
}}
[data-testid="stTab"], [role="tab"] {{ color: {palette['muted']}; }}
[data-testid="stTab"][aria-selected="true"],
[role="tab"][aria-selected="true"] {{ color: {palette['primary']}; }}
[data-baseweb="tab-highlight"], [data-testid="stTabHighlight"] {{
    background-color: {palette['primary']};
}}
[data-baseweb="tab-border"], [data-testid="stTabBorder"] {{
    background-color: {palette['border']};
}}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] details {{
    background-color: {palette['secondary_background']};
    color: {palette['text']};
}}
[data-testid="stProgress"] div[role="progressbar"] > div {{
    background-color: {palette['primary']};
}}
[data-testid="stAlert"] {{
    color: {palette['text']};
    background-color: {palette['secondary_background']};
    border: 1px solid {palette['border']};
}}
[data-testid="stCaptionContainer"], .stCaption, small {{ color: {palette['muted']}; }}
input::placeholder, textarea::placeholder {{ color: {palette['muted']} !important; }}
:focus-visible {{
    outline: 2px solid {palette['primary']} !important;
    outline-offset: 2px;
}}
</style>
"""


def current_theme() -> str:
    return str(
        st.session_state.get(RUN_KEY)
        or st.session_state.get(STATE_KEY)
        or DEFAULT_THEME
    )


def other_theme(mode: str | None = None) -> str:
    return LIGHT if (mode or current_theme()) == DARK else DARK


def init_theme(controller: Any) -> str:
    """Resolve the mode for this run from a queued switch, then the cookie.

    The cookie component often has not answered yet on the very first render of
    a fresh page load, so a missing value must never be *cached* as "dark" —
    otherwise a reload would silently discard the viewer's choice. It is only
    used as the fallback for this one run.
    """
    pending = st.session_state.pop(PENDING_KEY, None)
    if pending in (DARK, LIGHT):
        st.session_state[STATE_KEY] = pending
        st.session_state[RUN_KEY] = pending
        st.session_state[CHOSEN_KEY] = True
        _store(controller, pending)
        return pending

    if not st.session_state.get(CHOSEN_KEY):
        stored = None
        try:
            stored = controller.get(THEME_COOKIE)
        except Exception:  # noqa: BLE001 - the component may not have answered yet
            stored = None
        if stored in (DARK, LIGHT):
            st.session_state[STATE_KEY] = stored

    resolved = str(st.session_state.get(STATE_KEY, DEFAULT_THEME))
    st.session_state[RUN_KEY] = resolved
    return resolved


def _store(controller: Any, mode: str) -> None:
    try:
        controller.set(
            THEME_COOKIE,
            mode,
            path=COOKIE_PATH,
            secure=COOKIE_SECURE,
            same_site="strict",
        )
    except Exception:  # noqa: BLE001 - a browser that refuses the cookie still works
        pass


def apply_theme(mode: str | None = None) -> str:
    """Inject the palette for this run and expose it as a test anchor."""
    resolved = mode or current_theme()
    st.markdown(_stylesheet(resolved), unsafe_allow_html=True)
    st.markdown(
        f'<span data-testid="theme-mode" style="display:none">{resolved}</span>',
        unsafe_allow_html=True,
    )
    return resolved


def request_theme(mode: str) -> None:
    """Queue a switch; the next run stores it in the cookie and repaints."""
    st.session_state[PENDING_KEY] = mode


def theme_toggle(key: str = "theme_toggle", label_prefix: str = "") -> None:
    """The switch itself. Usable on login screens and inside the sidebar."""
    mode = current_theme()
    target = other_theme(mode)
    caption = "Светлая тема" if target == LIGHT else "Тёмная тема"
    icon = "☀️" if target == LIGHT else "🌙"
    if st.button(
        f"{icon} {label_prefix}{caption}",
        key=key,
        use_container_width=True,
        help="Переключить оформление интерфейса",
    ):
        request_theme(target)
        st.rerun()
