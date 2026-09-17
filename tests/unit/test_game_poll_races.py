"""Deterministic second-await races against the real participant editor."""

import asyncio
from copy import deepcopy

import pytest

from src.aml_workshop_simulator.ui.nicegui.client import APIError
from src.aml_workshop_simulator.ui.nicegui.game import GameEditor


def state(round_id, amount, revision=1):
    return {
        "round": {
            "id": round_id,
            "config_version": 1,
            "status": "active",
            "game_config": {},
        },
        "can_edit": True,
        "can_submit": False,
        "scenario": {
            "status": "editing",
            "revision": revision,
            "steps": [{
                "step_id": f"00000000-0000-0000-0000-{round_id:012d}",
                "card": {"id": round_id * 100 + 1, "code": f"card_{round_id}", "version": 1},
                "amount": amount,
                "context": {},
                "action_details": {},
            }],
        },
    }


class Transport:
    """Only HTTP is replaced; events choose exactly when cards complete."""

    def __init__(self, states, blocked_round=1, *, fail_cards=False):
        self.states = list(states)
        self.blocked_round = blocked_round
        self.fail_cards = fail_cards
        self.cards_entered = asyncio.Event()
        self.release_cards = asyncio.Event()

    async def request(self, method, path, **kwargs):
        if method == "GET" and path == "rounds/current/state":
            return deepcopy(self.states.pop(0))
        if method == "GET" and path.endswith("/cards"):
            round_id = int(path.split("/")[1])
            if round_id == self.blocked_round:
                self.cards_entered.set()
                await self.release_cards.wait()
                if self.fail_cards:
                    raise APIError("cards unavailable", status=503)
            return [{"id": round_id * 100 + 1, "code": f"card_{round_id}", "version": 1}]
        if method == "PUT" and path == "rounds/1/scenario":
            return {
                "status": "editing",
                "revision": kwargs["body"]["expected_revision"] + 1,
                "steps": deepcopy(kwargs["body"]["steps"]),
            }
        raise AssertionError((method, path))


def loaded_editor(api):
    initial = state(1, "100.00")
    record = {
        "key": [1, 1],
        "steps": deepcopy(initial["scenario"]["steps"]),
        "revision": 1,
        "dirty": False,
    }
    persisted = []
    editor = GameEditor(api, "test-session", record, lambda: persisted.append(deepcopy(record)))
    editor.state = initial
    return editor, persisted


def test_older_cards_response_cannot_replace_newer_round():
    async def run():
        api = Transport([state(1, "100.00"), state(2, "200.00"), state(2, "200.00")])
        editor = GameEditor(api, "test-session", {}, lambda: None)
        older = asyncio.create_task(editor.poll())
        await api.cards_entered.wait()
        await editor.poll()
        api.release_cards.set()
        await older
        assert editor.record["key"] == [2, 1]
        assert editor.state["round"]["id"] == 2
        assert editor.steps[0]["card"]["id"] == 201
        assert editor.cards[0]["id"] == 201
        await editor.poll()
        assert editor.cards[0]["id"] == 201

    asyncio.run(asyncio.wait_for(run(), 5))


def test_cards_response_cannot_roll_back_completed_save():
    async def run():
        api = Transport([state(1, "100.00")])
        editor, persisted = loaded_editor(api)
        older = asyncio.create_task(editor.poll())
        await api.cards_entered.wait()
        editor.steps[0]["amount"] = "150.00"
        editor.changed()
        assert await editor.write()
        saved = deepcopy(editor.record)
        writes = len(persisted)
        api.release_cards.set()
        await older
        assert editor.record == saved
        assert editor.record["revision"] == 2
        assert editor.steps[0]["amount"] == "150.00"
        assert len(persisted) == writes
        assert not editor.dirty and not editor.conflict

    asyncio.run(asyncio.wait_for(run(), 5))


def test_failed_round_cards_fetch_keeps_previous_snapshot_and_draft():
    async def run():
        api = Transport([state(2, "200.00"), state(2, "200.00")], 2, fail_cards=True)
        editor, persisted = loaded_editor(api)
        editor.cards = [{"id": 101}]
        editor.steps[0]["amount"] = "150.00"
        editor.changed()
        editor.record["pending"] = {"method": "PUT", "path": "rounds/1/scenario", "body": {}}
        editor.preview = {"can_submit": True}
        editor.preview_version = editor.version
        before = deepcopy((editor.record, editor.state, editor.cards, editor.preview))
        generation = editor.generation
        writes = len(persisted)
        api.release_cards.set()
        with pytest.raises(APIError):
            await editor.poll()
        assert (editor.record, editor.state, editor.cards, editor.preview) == before
        assert editor.generation == generation
        assert len(persisted) == writes
        api.fail_cards = False
        await editor.poll()
        assert editor.record["key"] == [2, 1]
        assert editor.cards[0]["id"] == 201
        assert editor.steps[0]["amount"] == "200.00"
        assert not editor.record.get("pending")
        assert editor.preview is None

    asyncio.run(asyncio.wait_for(run(), 5))


def test_round_transition_is_not_visible_while_cards_are_loading():
    async def run():
        api = Transport([state(2, "200.00")], 2)
        editor, _ = loaded_editor(api)
        older = asyncio.create_task(editor.poll())
        await api.cards_entered.wait()
        assert editor.record["key"] == [1, 1]
        assert editor.generation == 0
        editor.steps[0]["amount"] = "150.00"
        editor.changed()
        assert await editor.write()
        api.release_cards.set()
        await older
        assert editor.record["key"] == [1, 1]
        assert editor.record["revision"] == 2
        assert editor.steps[0]["amount"] == "150.00"

    asyncio.run(asyncio.wait_for(run(), 5))


def test_edit_during_cards_fetch_is_preserved_with_revision_conflict():
    async def run():
        api = Transport([state(1, "200.00", revision=2)])
        editor, _ = loaded_editor(api)
        older = asyncio.create_task(editor.poll())
        await api.cards_entered.wait()
        editor.steps[0]["amount"] = "150.00"
        editor.changed()
        api.release_cards.set()
        await older
        assert editor.steps[0]["amount"] == "150.00"
        assert editor.record["revision"] == 1
        assert editor.dirty and editor.conflict
        assert editor.state["scenario"]["revision"] == 2

    asyncio.run(asyncio.wait_for(run(), 5))
