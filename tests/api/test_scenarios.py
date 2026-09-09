"""A submission is one immutable command, independent of autosave."""

from uuid import uuid4

import pytest


def test_direct_submission_and_retry(
    request_api, player, active_round, chain, command, sql
):
    path = f"/rounds/{active_round}/scenario"
    headers = player["headers"]
    payload = command(chain())
    submitted = request_api("POST", path + "/submit", headers, payload)
    assert submitted["status"] == "submitted" and submitted["revision"] == 1
    assert not submitted["can_edit"] and not submitted["can_submit"]
    assert len(submitted["steps"]) == 9 and submitted["blockers"] == []
    assert request_api("POST", path + "/submit", headers, payload) == submitted
    for changed in (
        {**payload, "client_mutation_id": str(uuid4())},
        {**payload, "steps": []},
    ):
        request_api("POST", path + "/submit", headers, changed, 409)
    request_api("PUT", path, headers, command(chain(), 1), 409)
    assert request_api("GET", path, headers) == submitted
    assert (
        sql(
            "SELECT count(*) AS n FROM audit_events WHERE event_type='scenario_submitted'"
        )[0]["n"]
        == 1
    )


@pytest.mark.parametrize("saved_first", [False, True])
def test_invalid_submit_preserves_attempt(
    request_api, player, active_round, chain, command, saved_first
):
    path = f"/rounds/{active_round}/scenario"
    h = player["headers"]
    before = request_api("PUT", path, h, command(chain(1))) if saved_first else None
    revision = before["revision"] if before else 0
    error = request_api("POST", path + "/submit", h, command([], revision), 400)
    assert error["code"] == "scenario_validation_failed"
    assert request_api("GET", path, h) == before
    assert (
        request_api("POST", path + "/submit", h, command(chain(), revision))["status"]
        == "submitted"
    )


def test_autosave_revision_and_uuid_conflicts(
    request_api, player, active_round, chain, command
):
    path = f"/rounds/{active_round}/scenario"
    h = player["headers"]
    payload = command(chain(1))
    saved = request_api("PUT", path, h, payload)
    assert saved["can_edit"] and not saved["can_submit"]
    assert request_api("PUT", path, h, payload) == saved
    request_api("PUT", path, h, {**payload, "steps": chain(2)}, 409)
    request_api("PUT", path, h, command(chain(2)), 409)
    request_api("POST", path + "/submit", h, command(chain()), 409)
    assert request_api("GET", path, h) == saved
    updated = request_api("PUT", path, h, command(chain(), 1))
    assert updated["revision"] == 2 and updated["can_submit"]
    assert (
        request_api("POST", path + "/submit", h, command(updated["steps"], 2))["status"]
        == "submitted"
    )


def test_preview_and_page_reload(request_api, player, active_round, chain, command):
    path = f"/rounds/{active_round}/scenario"
    h = player["headers"]
    steps = chain()
    preview = request_api("POST", path + "/preview", h, {"steps": steps})
    assert preview["can_submit"] and not preview["blockers"]
    assert request_api("GET", path, h) is None
    saved = request_api("PUT", path, h, command(steps))
    assert saved["resources"] == preview["resources"]
    assert all(
        all(value is not None for value in step["context"].values())
        for step in saved["steps"]
    )
    assert request_api("GET", "/rounds/current/state", h)["scenario"] == saved


@pytest.mark.parametrize(
    "defect,status",
    [
        ("frequency", 422),
        ("negative_amount", 422),
        ("fraction", 422),
        ("duplicate_step", 422),
        ("unknown_card", 422),
        ("missing_goal", 400),
    ],
)
def test_invalid_cards_and_chains(
    request_api, player, active_round, chain, command, defect, status
):
    steps = chain()
    if defect == "frequency":
        steps[0]["frequency"] = 3
    elif defect == "negative_amount":
        steps[0]["amount"] = "-1"
    elif defect == "fraction":
        steps[0]["amount"] = "1.001"
    elif defect == "duplicate_step":
        steps[1]["step_id"] = steps[0]["step_id"]
    elif defect == "unknown_card":
        steps[0]["card"]["id"] = 999999
    else:
        steps = steps[:1]
    path = f"/rounds/{active_round}/scenario"
    request_api("POST", path + "/submit", player["headers"], command(steps), status)
    assert request_api("GET", path, player["headers"]) is None
