from src.aml_workshop_simulator.ui.nicegui.storage_retention import (
    prune_storage,
    touch_tab,
)


def test_many_tabs_keep_dirty_pending_and_live_guards():
    store = {
        "pages": {str(i): f"client-{i}" for i in range(20)},
        "tab_activity": {str(i): i for i in range(20)},
        "workspace_play": {str(i): {"steps": [], "dirty": i == 0} for i in range(20)},
    }
    store["workspace_play"]["1"]["pending"] = {"idempotency_key": "unconfirmed"}
    prune_storage(store, {"client-2"}, now=30, max_records=10, ttl_seconds=100)
    assert set(store["pages"]) == {"0", "1", "2", *map(str, range(13, 20))}
    assert store["pages"]["2"] == "client-2"
    assert store["workspace_play"]["1"]["pending"]["idempotency_key"] == "unconfirmed"


def test_ttl_and_reload_reconnect_preserve_active_tokens():
    store = {
        "pages": {"reload": "old", "live": "live-client", "closed": "gone"},
        "tab_activity": {"reload": 0, "live": 0, "closed": 0},
        "workspace_play": {"reload": {"dirty": True}, "closed": {"dirty": False}},
    }
    store["pages"]["reload"] = "new"
    touch_tab(store, "reload", now=100)
    prune_storage(store, {"new", "live-client"}, now=100, ttl_seconds=10)
    assert store["pages"] == {"reload": "new", "live": "live-client"}
    assert store["workspace_play"] == {"reload": {"dirty": True}}
    prune_storage(store, {"new", "live-client"}, now=1000, ttl_seconds=10)
    assert store["pages"]["reload"] == "new"


def test_limit_is_soft_for_unsaved_or_active_pages():
    store = {
        "pages": {str(i): str(i) for i in range(15)},
        "workspace_play": {str(i): {"dirty": True} for i in range(15)},
    }
    prune_storage(store, set(), now=100, max_records=10, ttl_seconds=1)
    assert len(store["workspace_play"]) == 15
    assert len(store["pages"]) == 15


def test_clean_legacy_records_can_be_reloaded_from_server():
    store = {"pages": {"old": "gone"}, "workspace_play": {"old": {"dirty": False}}}
    prune_storage(store, set(), now=1000, ttl_seconds=10)
    assert store["pages"] == store["workspace_play"] == store["tab_activity"] == {}
