"""Audit survives deletion of game data, and expected failures stay actionable."""

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.services import scoring_run


def test_restart_preserves_access_and_scenario_audit(request_api, admin, player, active_round, chain, command, sql):
    scenario = request_api("POST", f"/rounds/{active_round}/scenario/submit", player["headers"], command(chain()))
    for blocked, revision in ((True, 1), (False, 2)):
        request_api("PUT", f"/admin/rounds/{active_round}/participants/{player['id']}/access", admin,
                    {"blocked": blocked, "reason": "Проверка сохранения истории", "expected_access_revision": revision})
    sql("INSERT INTO audit_events(actor_user_id, round_id, scenario_id, event_type, target_type, target_id, reason, created_at) "
        "VALUES(1, :rid, :sid, 'scenario_inspected', 'scenario', :target, 'Проверка сценария', now())",
        {"rid": active_round, "sid": scenario["id"], "target": str(scenario["id"])})
    before = sql("SELECT * FROM audit_events ORDER BY id")
    fresh = request_api("POST", f"/admin/rounds/{active_round}/restart", admin, status=201)
    events = {event["id"]: event for event in sql("SELECT * FROM audit_events ORDER BY id")}
    for previous in before:
        saved = events[previous["id"]]
        for key in ("actor_user_id", "event_type", "reason", "target_type", "target_id"):
            assert saved[key] == previous[key]
        if previous["round_id"]:
            assert saved["round_id"] is None
            assert saved["metadata"]["previous_round_id"] == active_round
        if previous["scenario_id"]:
            assert saved["scenario_id"] is None
            assert saved["metadata"]["previous_scenario_id"] == scenario["id"]
    restarted = next(e for e in events.values() if e["event_type"] == "round_restarted")
    assert restarted["metadata"]["previous_round_id"] == active_round
    assert restarted["metadata"]["new_round_id"] == fresh["id"]
    assert restarted["metadata"]["deleted_scenarios"] == 1
    assert sql("SELECT id FROM scenarios") == []


def test_access_without_round_revokes_session(request_api, admin, player, sql):
    sql("TRUNCATE rounds RESTART IDENTITY CASCADE")
    response = request_api("PUT", f"/admin/participants/{player['id']}/access", admin,
                           {"blocked": True, "reason": "Блокировка без текущей игры", "expected_access_revision": 1})
    assert response["is_blocked"] and response["access_revision"] == 2
    assert all(row["revoked_at"] is not None for row in sql("SELECT revoked_at FROM sessions WHERE user_id=:uid", {"uid": player["id"]}))
    event = sql("SELECT * FROM audit_events WHERE event_type='participant_blocked'")[0]
    assert event["round_id"] is None and event["target_id"] == str(player["id"])


def test_domain_scoring_error_is_preserved(request_api, admin, player, active_round, chain, command, monkeypatch, sql):
    request_api("POST", f"/rounds/{active_round}/scenario/submit", player["headers"], command(chain()))
    original = scoring_run.score_round

    async def fail_after_writes(*args, **kwargs):
        await original(*args, **kwargs)
        raise Conflict("Закреплённая модель недоступна.", code="model_unavailable")

    monkeypatch.setattr(scoring_run, "score_round", fail_after_writes)
    error = request_api("POST", f"/admin/rounds/{active_round}/score", admin, status=409)
    assert error["code"] == "model_unavailable"
    row = sql("SELECT status, scoring_error FROM rounds")[0]
    assert row["status"] == "closed"
    assert row["scoring_error"] == {key: error[key] for key in ("code", "message", "request_id")}
    assert sql("SELECT id FROM scoring_results") == []
    assert sql("SELECT status FROM scenarios")[0]["status"] == "submitted"


def test_failed_restart_rolls_back_audit_references(request_api, admin, active_round, sql, monkeypatch):
    from src.aml_workshop_simulator.services import admin_rounds
    before = {table: sql(f"SELECT * FROM {table} ORDER BY id") for table in ("rounds", "audit_events")}

    async def fail(*args, **kwargs):
        raise RuntimeError("Injected failure before commit")

    monkeypatch.setattr(admin_rounds, "record_event", fail)
    request_api("POST", f"/admin/rounds/{active_round}/restart", admin, status=500)
    assert {table: sql(f"SELECT * FROM {table} ORDER BY id") for table in before} == before


def test_cutoff_preserves_audit_of_discarded_draft(request_api, admin, player, active_round, chain, command, sql):
    scenario = request_api("PUT", f"/rounds/{active_round}/scenario", player["headers"], command(chain()))
    sql("INSERT INTO audit_events(actor_user_id, round_id, scenario_id, event_type, created_at) "
        "VALUES(1, :rid, :sid, 'draft_checked', now())", {"rid": active_round, "sid": scenario["id"]})
    request_api("POST", f"/admin/rounds/{active_round}/score", admin)
    event = sql("SELECT * FROM audit_events WHERE event_type='draft_checked'")[0]
    assert event["scenario_id"] is None
    assert event["metadata"]["previous_scenario_id"] == scenario["id"]


def test_audit_migration_preserves_populated_old_schema(api, sql):
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    before = sql("SELECT * FROM audit_events ORDER BY id")
    try:
        command.downgrade(config, "0001_current_schema")
        assert {row["confdeltype"] for row in sql("SELECT confdeltype::text AS confdeltype FROM pg_constraint WHERE conname IN ('audit_events_round_id_fkey', 'audit_events_scenario_id_fkey')")} == {"a"}
        command.upgrade(config, "head")
        assert {row["confdeltype"] for row in sql("SELECT confdeltype::text AS confdeltype FROM pg_constraint WHERE conname IN ('audit_events_round_id_fkey', 'audit_events_scenario_id_fkey')")} == {"n"}
        assert sql("SELECT * FROM audit_events ORDER BY id") == before
    finally:
        command.upgrade(config, "head")
