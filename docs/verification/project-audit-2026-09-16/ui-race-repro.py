"""Deterministic audit reproductions; imports GameEditor without modifying it.

Run from the repository root in PowerShell:
  $env:PYTHONUTF8='1'
  & .venv/Scripts/python.exe docs/verification/project-audit-2026-09-16/ui-race-repro.py

The fake transport uses asyncio.Event barriers, not timing assumptions. A zero
exit status means the documented faulty outcomes were reproduced, not that the
editor passed a regression test. This script writes its observed JSON output
next to itself and performs no network or database operations.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.aml_workshop_simulator.ui.nicegui.game import GameEditor  # noqa: E402


def scenario(round_id, amount, revision=1):
    return {
        "status": "editing",
        "revision": revision,
        "steps": [{
            "step_id": f"00000000-0000-0000-0000-{round_id:012d}",
            "card": {"id": round_id * 100 + 1, "code": f"audit_card_{round_id}", "version": 1},
            "amount": amount,
            "context": {},
            "action_details": {},
        }],
    }


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
        "scenario": scenario(round_id, amount, revision),
    }


def snapshot(editor):
    return deepcopy(
        {
            "record": editor.record,
            "state_round_id": (editor.state.get("round") or {}).get("id"),
            "state_scenario": editor.state.get("scenario"),
            "cards": editor.cards,
            "poll_sequence": editor.poll_sequence,
            "write_sequence": editor.write_sequence,
            "generation": editor.generation,
            "conflict": editor.conflict,
        }
    )


class FakeAPI:
    def __init__(self, states, *, blocked_card_round):
        self.states = list(states)
        self.blocked_card_round = blocked_card_round
        self.cards_entered = asyncio.Event()
        self.release_cards = asyncio.Event()
        self.calls = []
        self.saved_scenario = None

    async def request(self, method, path, **kwargs):
        call = {"method": method, "path": path}
        if "body" in kwargs:
            call["body"] = deepcopy(kwargs["body"])
        self.calls.append(call)
        if path == "rounds/current/state":
            assert method == "GET" and self.states, call
            return deepcopy(self.states.pop(0))
        if path.endswith("/cards"):
            round_id = int(path.split("/")[1])
            if round_id == self.blocked_card_round:
                self.cards_entered.set()
                await self.release_cards.wait()
            return [{"id": round_id * 100 + 1, "audit_round_id": round_id}]
        if method == "PUT" and path.endswith("/scenario"):
            self.saved_scenario = {
                "status": "editing",
                "revision": kwargs["body"]["expected_revision"] + 1,
                "steps": deepcopy(kwargs["body"]["steps"]),
            }
            return deepcopy(self.saved_scenario)
        raise AssertionError(call)


async def two_polls_cross_rounds():
    api = FakeAPI(
        [state(1, "100.00"), state(2, "200.00"), state(2, "200.00")],
        blocked_card_round=1,
    )
    persisted = []
    record = {}
    editor = GameEditor(api, "audit-fake-session", record, lambda: persisted.append(deepcopy(record)))
    older_poll = asyncio.create_task(editor.poll())
    await api.cards_entered.wait()
    # The first poll has already cleared the record and installed key [1, 1].
    await editor.poll()
    after_newer_poll = snapshot(editor)
    assert after_newer_poll["record"]["key"] == [2, 1]
    assert after_newer_poll["state_round_id"] == 2
    api.release_cards.set()
    await older_poll
    after_older_poll = snapshot(editor)
    # A single editor now combines the key of round 2 with data from round 1.
    assert after_older_poll["record"]["key"] == [2, 1]
    assert after_older_poll["state_round_id"] == 1
    assert after_older_poll["record"]["steps"][0]["card"]["id"] == 101
    assert after_older_poll["cards"][0]["audit_round_id"] == 1
    # An ordinary subsequent poll repairs state/steps but never reloads cards:
    # the key matches and the stale cards list is nonempty.
    await editor.poll()
    after_recovery_poll = snapshot(editor)
    assert after_recovery_poll["state_round_id"] == 2
    assert after_recovery_poll["record"]["steps"][0]["card"]["id"] == 201
    assert after_recovery_poll["cards"][0]["audit_round_id"] == 1
    return {
        "bug_reproduced": True,
        "schedule": [
            "Poll A reads round 1 and suspends inside GET rounds/1/cards",
            "Poll B reads round 2, fetches its cards, and completes",
            "Poll A resumes and overwrites cards, state, steps, and revision",
            "Poll C reads round 2; state/steps recover, but cards stay from round 1",
        ],
        "after_newer_poll": after_newer_poll,
        "after_older_poll": after_older_poll,
        "after_recovery_poll": after_recovery_poll,
        "persisted_records": persisted,
        "requests": api.calls,
        "violated_invariant": "The record key, state, steps, and cards must belong to one round.",
    }


async def poll_crosses_successful_save():
    old_state = state(1, "100.00", revision=1)
    api = FakeAPI([old_state], blocked_card_round=1)
    record = {"key": [1, 1], "steps": deepcopy(old_state["scenario"]["steps"]), "revision": 1, "dirty": False}
    persisted = []
    editor = GameEditor(api, "audit-fake-session", record, lambda: persisted.append(deepcopy(record)))
    editor.state = deepcopy(old_state)
    # Empty cards are supported by the retry branch at game.py:102-103.
    older_poll = asyncio.create_task(editor.poll())
    await api.cards_entered.wait()
    editor.steps[0]["amount"] = "150.00"
    editor.changed()
    assert await editor.write()
    after_save = snapshot(editor)
    assert after_save["record"]["revision"] == 2
    assert after_save["record"]["steps"][0]["amount"] == "150.00"
    api.release_cards.set()
    await older_poll
    after_older_poll = snapshot(editor)
    assert after_older_poll["record"]["revision"] == 1
    assert after_older_poll["record"]["steps"][0]["amount"] == "100.00"
    assert not after_older_poll["record"]["dirty"]
    assert not after_older_poll["conflict"]
    assert api.saved_scenario["revision"] == 2
    assert api.saved_scenario["steps"][0]["amount"] == "150.00"
    return {
        "bug_reproduced": True,
        "schedule": [
            "Poll A reads revision 1 and suspends while fetching missing cards",
            "The user edits the amount to 150.00 and saves revision 2 successfully",
            "Poll A resumes and silently restores amount 100.00/revision 1 locally",
        ],
        "after_save": after_save,
        "after_older_poll": after_older_poll,
        "server_saved_scenario": api.saved_scenario,
        "persisted_records": persisted,
        "requests": api.calls,
        "violated_invariant": "A successful write must invalidate an earlier poll before it updates local state.",
        "limit": "The fake server preserves revision 2; this reproduction establishes local rollback, not server data loss.",
    }


async def main():
    source = Path(inspect.getfile(GameEditor))
    results = {
        "audit_date": "2026-09-16",
        "python": sys.version,
        "source_path": str(source.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "uses_unmodified_production_class": True,
        "uses_network_or_database": False,
        "round_change_race": await asyncio.wait_for(two_polls_cross_rounds(), 5),
        "save_race": await asyncio.wait_for(poll_crosses_successful_save(), 5),
    }
    output = json.dumps(results, ensure_ascii=False, indent=2)
    Path(__file__).with_name("ui-race.json").write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
