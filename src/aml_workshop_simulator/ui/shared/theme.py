"""The palette both applications draw with, resolved for the active theme.

Streamlit publishes nothing a stylesheet can read: `--border-color`,
`--text-color` and `--primary-color` resolve to the empty string, and the
viewer's Light/Dark choice is independent of `prefers-color-scheme`, so a media
query would follow the operating system rather than the app. The colours are
therefore resolved here, from the same values `.streamlit/config.toml` gives
Streamlit itself, and inlined into the page on every run.
"""

from __future__ import annotations

import streamlit as st

#: Mirrors `[theme.light]` and `[theme.dark]` in `.streamlit/config.toml`.
#: `primary` doubles as the accent for headings, so it has to clear WCAG AA
#: (4.5:1) against that theme's background: 4.9:1 light, 9.0:1 dark.
PALETTES = {
    "light": {
        "primary": "#0E7A67",
        "line": "#DCE4E1",
        "danger": "#C62828",
        "surface": "rgba(25, 36, 32, .05)",
    },
    "dark": {
        "primary": "#4CC7AB",
        "line": "#33413C",
        "danger": "#FF6B6B",
        "surface": "rgba(232, 239, 236, .06)",
    },
}


def active_theme() -> str:
    """`"dark"` or `"light"` — whichever Streamlit is rendering right now."""
    theme = getattr(st.context, "theme", None)
    return "dark" if getattr(theme, "type", None) == "dark" else "light"


def palette_css() -> str:
    """The `--aml-*` custom properties, as a `<style>` block."""
    palette = PALETTES[active_theme()]
    return (
        "<style>\n"
        ':root, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {\n'
        f"    --aml-primary: {palette['primary']};\n"
        f"    --aml-line: {palette['line']};\n"
        f"    --aml-danger: {palette['danger']};\n"
        f"    --aml-surface: {palette['surface']};\n"
        "    --aml-muted: color-mix(in srgb, currentColor 62%, transparent);\n"
        "    --aml-ok: var(--aml-primary);\n"
        "}\n"
        "</style>"
    )
