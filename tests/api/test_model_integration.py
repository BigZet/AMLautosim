from unittest.mock import patch
from scripts.check_expanded_balance import demo_steps
from src.aml_workshop_simulator.services.model_scoring import get_model_scorer


def test_model_round_atomic_retry_and_no_early_explanation(
    request_api, admin, round_id, player_factory, command, sql
):
    config = request_api("GET", "/admin/rounds/current", admin)["game_config"]
    assert (
        config["schema_version"] == 8
        and config["risk_model"] == get_model_scorer().identity
    )
    request_api("POST", f"/admin/rounds/{round_id}/start", admin)
    players = []
    for variant in ["baseline", "purchase"]:
        player = player_factory(variant)
        players.append(player)
        steps = demo_steps(config, variant)
        path = f"/rounds/{round_id}/scenario"
        preview = request_api(
            "POST", path + "/preview", player["headers"], {"steps": steps}
        )
        assert "risk_score" not in str(preview) and "explanation" not in str(preview)
        request_api("POST", path + "/submit", player["headers"], command(steps))
        assert (
            request_api("GET", "/rounds/current/state", player["headers"])["result"]
            is None
        )
    scorer = get_model_scorer()
    original = scorer.score
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("SHAP unavailable")
        return original(*args, **kwargs)

    with patch.object(scorer, "score", side_effect=fail_second):
        request_api("POST", f"/admin/rounds/{round_id}/score", admin, status=500)
    assert sql("SELECT * FROM scoring_results") == []
    assert sql("SELECT status FROM rounds")[0]["status"] == "closed"
    request_api("POST", f"/admin/rounds/{round_id}/score", admin)
    assert len(sql("SELECT * FROM scoring_results")) == 2
    for player in players:
        state = request_api("GET", "/rounds/current/state", player["headers"])
        explanation = state["result"]["explanation"]
        assert (
            explanation["method"] == "catboost-tree-shap"
            and len(explanation["factors"]) == 84
        )
        assert (
            request_api("GET", "/rounds/current/state", player["headers"])["result"]
            == state["result"]
        )
        board = request_api("GET", f"/rounds/{round_id}/leaderboard", player["headers"])
        assert "explanation" not in str(board)
    with patch.object(
        scorer, "score", side_effect=AssertionError("must not recalculate")
    ):
        request_api("POST", f"/admin/rounds/{round_id}/score", admin)
    assert len(sql("SELECT * FROM scoring_results")) == 2


def test_100_scenarios_keep_state_requests_responsive(
    request_api, admin, round_id, player, command, sql
):
    import time
    from concurrent.futures import ThreadPoolExecutor

    config = request_api("GET", "/admin/rounds/current", admin)["game_config"]
    request_api("POST", f"/admin/rounds/{round_id}/start", admin)
    request_api(
        "POST",
        f"/rounds/{round_id}/scenario/submit",
        player["headers"],
        command(demo_steps(config)),
    )
    # Replicate one valid fixture in the disposable test DB; this is a load check,
    # not additional independent model-quality evidence.
    sql("""INSERT INTO users (email, display_name, hashed_password, role, is_blocked, access_revision, failed_login_count)
           SELECT 'load-' || n || '@example.com', 'Load ' || n, 'unused', 'participant', false, 0, 0
           FROM generate_series(1,99) n""")
    sql("""INSERT INTO scenarios (round_id, participant_id, status, steps, resource_snapshot, revision, updated_at, submitted_at)
           SELECT s.round_id,u.id,'submitted',s.steps,s.resource_snapshot,1,now(),now()
           FROM users u CROSS JOIN (SELECT * FROM scenarios LIMIT 1) s
           WHERE u.email LIKE 'load-%'""")
    latencies = []
    observed_scoring = False
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            request_api, "POST", f"/admin/rounds/{round_id}/score", admin
        )
        while not future.done():
            before = time.perf_counter()
            state = request_api("GET", "/rounds/current/state", player["headers"])
            latencies.append(time.perf_counter() - before)
            if state["round"]["status"] == "scoring":
                observed_scoring = True
                assert state["result"] is None
            time.sleep(0.05)
        result = future.result()
    elapsed = time.perf_counter() - started
    assert result["scored_count"] == 100 and elapsed < 60
    assert observed_scoring and max(latencies) < 2
    print(
        {
            "scenarios": 100,
            "seconds": elapsed,
            "max_state_latency_seconds": max(latencies),
            "requests": len(latencies),
        }
    )


def test_new_starts_can_be_disabled_without_old_rule_mode(
    monkeypatch, request_api, admin, round_id
):
    from src.aml_workshop_simulator.core.config import settings

    assert (
        request_api("GET", "/admin/game-config/default", admin)["schema_version"] == 10
    )
    request_api("GET", "/admin/game-config/default?schema_version=7", admin, status=422)
    monkeypatch.setattr(settings, "EXPANDED_ROUNDS_ENABLED", False)
    assert (
        request_api("GET", "/admin/game-config/editor-metadata", admin)[
            "available_contracts"
        ]
        == []
    )
    request_api("POST", f"/admin/rounds/{round_id}/start", admin, status=409)
    assert request_api("GET", "/admin/rounds/current", admin)["status"] == "draft"


def test_readiness_exposes_loaded_model_identity(api):
    result = api.get("/health/ready")
    assert result.status_code == 200
    from src.aml_workshop_simulator.services.game_classifier import get_game_classifier
    assert result.json()["checks"]["model"] == get_game_classifier().identity
