"""Bound inactive clean tab state; unsaved commands and live page guards win."""

import time


def touch_tab(storage, tab_id, *, now=None):
    activity = dict(storage.get("tab_activity", {}))
    activity[tab_id] = time.time() if now is None else now
    storage["tab_activity"] = activity


def prune_storage(
    storage, active_client_ids, *, now=None, max_records=10, ttl_seconds=7 * 86400
):
    now = time.time() if now is None else now
    keys = ("pages", "workspace_play", "workspace_admin", "tab_activity")
    values = {key: dict(storage.get(key, {})) for key in keys}
    tabs = set().union(*(set(value) for value in values.values()))
    protected = {
        tab
        for tab in tabs
        if values["pages"].get(tab) in active_client_ids
        or any(
            record.get("dirty") or record.get("pending")
            for key in ("workspace_play", "workspace_admin")
            if (record := values[key].get(tab, {}))
        )
    }
    candidates = sorted(
        tabs - protected, key=lambda tab: values["tab_activity"].get(tab, 0)
    )
    remaining = len(tabs)
    for tab in candidates:
        expired = now - values["tab_activity"].get(tab, 0) >= ttl_seconds
        if expired or remaining > max_records:
            for value in values.values():
                value.pop(tab, None)
            remaining -= 1
    for key, value in values.items():
        if key in storage or value:
            storage[key] = value
    # A metadata map also upgrades clean legacy records without timestamps.
    storage["tab_activity"] = values["tab_activity"]


def retain_live_tabs(storage, tab_id):
    from nicegui.client import Client

    touch_tab(storage, tab_id)
    # Includes clients awaiting reconnect_timeout; a transient disconnect must
    # not remove the page ownership token or its workspace.
    prune_storage(storage, set(Client.instances))
