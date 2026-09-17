"""Demo orchestration tests use a fake HTTP service, never acceptance scores."""

from copy import deepcopy
import importlib
import json
from pathlib import Path

import httpx
import pytest


def module():
    return importlib.import_module("scripts.create_aml_demo")


def book():
    return json.loads(
        Path("resources/aml_dataset/aml-v1/demo-frozen/v2/casebook.json").read_bytes()
    )


def urls():
    return (
        [f"http://127.0.0.1:{59000 + i}" for i in range(5)],
        [f"http://127.0.0.1:{59100 + i}" for i in range(5)],
    )


def test_targets_require_five_distinct_local_apps():
    m = module()
    api, ui = urls()
    assert len(m.validate_targets(api, ui)) == 5
    for bad in (
        [api[0]] * 5,
        api[:4],
        ["https://unrelated.example"] + api[1:],
        [api[0] + "/?token=secret"] + api[1:],
    ):
        with pytest.raises(ValueError):
            m.validate_targets(bad, ui)


def test_card_database_ids_can_change_without_changing_frozen_economics():
    m = module()
    public = book()["rounds"][0]["cases"][0]["record"]["public_snapshot"]
    saved = deepcopy(public["config"])
    for card in saved["card_snapshots"]:
        card["id"] += 1000
    steps = m.server_steps(public, saved)
    assert [s["card"]["id"] for s in steps] == [
        s["card"]["id"] + 1000 for s in public["steps"]
    ]
    assert public["steps"] != steps
    saved["resources"]["initial_balance"] = "180001.00"
    with pytest.raises(ValueError, match="config"):
        m.server_steps(public, saved)


@pytest.mark.parametrize("change", ["fee_rate", "max_occurrences"])
def test_changed_server_card_semantics_are_rejected(change):
    m = module()
    public = book()["rounds"][0]["cases"][0]["record"]["public_snapshot"]
    saved = deepcopy(public["config"])
    saved["card_snapshots"][0][change] = "0.1234" if change == "fee_rate" else 999
    with pytest.raises(ValueError, match="card"):
        m.server_steps(public, saved)


def test_http_errors_do_not_echo_response_or_credentials():
    m = module()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(400, json={"detail": "SECRET-CREDENTIAL"})
    )
    with httpx.Client(
        transport=transport, base_url="http://127.0.0.1/api/v1/"
    ) as client:
        with pytest.raises(RuntimeError) as error:
            m.Api(client).call(
                "POST", "auth/login", payload={"password": "SECRET-CREDENTIAL"}
            )
    assert "SECRET-CREDENTIAL" not in str(error.value)


def test_only_equivalent_serialization_can_rebind_context_hash():
    m = module()
    frozen = book()["rounds"][0]["cases"][0]["record"]["public_snapshot"]["config"]
    saved = m.input_config(frozen)
    expected = {
        "context_sha256": m.canonical_hash(frozen["behavior"]),
        "aml_probability": 0.125,
    }
    actual = m.server_explanation(expected, frozen, saved)
    assert actual["context_sha256"] == m.canonical_hash(saved["behavior"])
    assert actual["context_sha256"] != expected["context_sha256"]
    assert actual["aml_probability"] == expected["aml_probability"]
    assert expected["context_sha256"] == m.canonical_hash(frozen["behavior"])
    with pytest.raises(ValueError, match="another frozen context"):
        m.server_explanation({**expected, "context_sha256": "0" * 64}, frozen, saved)
    changed = deepcopy(saved)
    changed["behavior"]["history"]["operations"][0]["amount"] = "1.00"
    with pytest.raises(ValueError, match="context changed"):
        m.server_explanation(expected, frozen, changed)


def test_existing_output_is_refused_before_any_input_or_network(tmp_path):
    m = module()
    with pytest.raises(FileExistsError):
        m.create_demo(
            dataset=tmp_path / "missing",
            package=tmp_path / "missing",
            casebook=tmp_path / "missing",
            api_urls=urls()[0],
            ui_urls=urls()[1],
            output=tmp_path,
        )


def test_nonlocal_private_output_is_rejected_before_input_loading(tmp_path):
    m = module()
    with pytest.raises(ValueError, match="local-run"):
        m.create_demo(
            dataset=tmp_path / "missing",
            package=tmp_path / "missing",
            casebook=tmp_path / "missing",
            api_urls=urls()[0],
            ui_urls=urls()[1],
            output=tmp_path / "public",
        )


@pytest.fixture
def fake_games(tmp_path, monkeypatch):
    """Network protocol simulation; fixed fake p must never be acceptance data."""
    m = module()
    value = book()
    fixture = json.loads(Path("tests/fixtures/scoring-api/result-v4.json").read_bytes())

    class FakeModel:
        model_identity = fixture["explanation"]["model_identity"]

        def predict(self, *, steps, config):
            result = deepcopy(fixture["explanation"])
            result["context_sha256"] = m.canonical_hash(config["behavior"])
            return result

    model = FakeModel()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setenv("AML_DEMO_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("AML_DEMO_ADMIN_PASSWORD", "PRIVATE-ADMIN-PASSWORD")
    monkeypatch.setattr(
        m,
        "load_inputs",
        lambda *args: (model, value, {"scope": "transport-fixture-only"}),
    )
    states = [
        {"round": None, "players": {}, "submissions": {}, "score_calls": 0}
        for _ in range(5)
    ]
    controls = {
        "occupied": None,
        "bad_ui": None,
        "fail_registration": None,
        "registrations": 0,
        "calls": [],
        "logouts": [],
    }

    def request(request):
        if request.url.path == "/health/live":
            return httpx.Response(
                503 if controls["bad_ui"] == request.url.port - 59100 else 200,
                text="ok",
            )
        index = request.url.port - 59000
        state = states[index]
        method, path = request.method, request.url.path.removeprefix("/api/v1/")
        data = json.loads(request.content) if request.content else None
        token = request.headers.get("X-Session-ID")
        controls["calls"].append((index, method, path, data))
        if path == "auth/login":
            audience = data["audience"]
            if audience == "play":
                assert data["email"] in state["players"]
            return httpx.Response(
                200,
                json={
                    "session_id": data["email"],
                    "audience": audience,
                    "user": {
                        "role": "admin" if audience == "admin" else "participant",
                        "id": 1
                        if audience == "admin"
                        else state["players"][data["email"]]["id"],
                    },
                },
            )
        if path == "auth/session" and method == "DELETE":
            controls["logouts"].append((index, token))
            return httpx.Response(204)
        if path == "admin/rounds/current":
            return httpx.Response(
                200,
                content=json.dumps(
                    {"id": 999} if controls["occupied"] == index else state["round"]
                ),
            )
        if path == "admin/rounds" and method == "POST":
            assert state["round"] is None
            saved = deepcopy(
                value["rounds"][index]["cases"][0]["record"]["public_snapshot"][
                    "config"
                ]
            )
            assert data["game_config"] == m.input_config(saved)
            for card in saved["card_snapshots"]:
                card["id"] += 1000
            saved["config_version"] = "fake-server-context"
            saved["risk_model"] = m.pin(model, saved)
            state["round"] = {
                "id": 1,
                "title": data["title"],
                "status": "draft",
                "game_config": saved,
            }
            return httpx.Response(201, json=state["round"])
        if path == "admin/rounds/1/start":
            state["round"]["status"] = "active"
            return httpx.Response(200, json=state["round"])
        if path == "auth/register":
            controls["registrations"] += 1
            if controls["registrations"] == controls["fail_registration"]:
                return httpx.Response(500, json={"detail": data["password"]})
            assert data["email"] not in state["players"]
            state["players"][data["email"]] = {**data, "id": len(state["players"]) + 1}
            return httpx.Response(201, json={"id": len(state["players"])})
        if path == "rounds/1/scenario/submit":
            assert token in state["players"]
            assert all(s["card"]["id"] > 1000 for s in data["steps"])
            assert data["expected_revision"] == 0
            state["submissions"][token] = data
            return httpx.Response(
                200,
                json={
                    "status": "submitted",
                    "round_id": 1,
                    "participant_id": state["players"][token]["id"],
                    "id": state["players"][token]["id"],
                },
            )
        if path == "admin/rounds/1/score":
            assert len(state["submissions"]) == 5
            state["round"]["status"] = "completed"
            state["score_calls"] += 1
            return httpx.Response(
                200,
                json={"status": "completed", "submitted_count": 5, "scored_count": 5},
            )
        if path == "rounds/1/result":
            assert state["round"]["status"] == "completed"
            result = deepcopy(fixture)
            result["explanation"] = model.predict(
                steps=state["submissions"][token]["steps"],
                config=state["round"]["game_config"],
            )
            result["scenario_id"] = state["players"][token]["id"]
            result["resources"] = m.ResourceSnapshotOut.model_validate(
                m.evaluate(
                    state["submissions"][token]["steps"], state["round"]["game_config"]
                )
            ).model_dump(mode="json")
            scores = m.probability_leaderboard_scores(
                0.09999,
                m.resource_score(result["resources"], state["round"]["game_config"]),
                state["round"]["game_config"],
            )
            result["scores"].update({k: str(v) for k, v in scores.items()})
            return httpx.Response(200, json=result)
        if path in {"admin/rounds/1/leaderboard", "rounds/1/leaderboard"}:
            return httpx.Response(
                200,
                json={
                    "rows": [
                        {
                            "email": email,
                            "display_name": p["display_name"],
                            "score_kind": "aml_probability",
                            "aml_probability": 0.09999,
                        }
                        for email, p in state["players"].items()
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {method} {path}")

    client = httpx.Client
    monkeypatch.setattr(
        m.httpx,
        "Client",
        lambda **kwargs: client(transport=httpx.MockTransport(request), **kwargs),
    )
    output = tmp_path / ".local-run" / "demo"

    def run():
        return m.create_demo(
            dataset=tmp_path / "unused",
            package=tmp_path / "unused",
            casebook=tmp_path / "unused",
            api_urls=urls()[0],
            ui_urls=urls()[1],
            output=output,
        )

    return run, states, controls, output


def test_five_games_keep_all_25_even_when_expected_bands_fail(fake_games):
    run, states, controls, output = fake_games
    report = run()
    assert report["status"] == "completed-with-band-failures"
    assert report["bands"]["clear_failed"] == 10
    assert len(report["bands"]["cases"]) == len(report["results"]) == 25
    assert all(s["score_calls"] == 2 and len(s["submissions"]) == 5 for s in states)
    assert len(controls["logouts"]) == 30
    access = json.loads((output / "private-access.json").read_bytes())
    assert len({p["email"] for p in access["players"]}) == 25
    assert all(p["round_id"] == 1 for p in access["players"])
    public = (output / "report.json").read_text(encoding="utf8") + (
        output / "index.html"
    ).read_text(encoding="utf8")
    assert access["organizer"]["password"] not in public
    assert all(p["password"] not in public for p in access["players"])
    assert all("restart" not in path for _, _, path, _ in controls["calls"])
    assert all(
        "author_truth" not in json.dumps(data) and "aml_label" not in json.dumps(data)
        for _, _, path, data in controls["calls"]
        if path != "auth/login"
    )


def test_all_targets_checked_before_creating_first_game(fake_games):
    run, states, controls, output = fake_games
    controls["occupied"] = 4
    with pytest.raises(ValueError, match="already contains"):
        run()
    assert all(s["round"] is None and not s["players"] for s in states)
    assert len(controls["logouts"]) == 5
    assert json.loads((output / "report.json").read_bytes())["status"] == "incomplete"


def test_partial_api_failure_preserves_credentials_and_full_frozen_roster(fake_games):
    run, states, controls, output = fake_games
    controls["fail_registration"] = 12
    with pytest.raises(RuntimeError, match="HTTP 500"):
        run()
    report = json.loads((output / "report.json").read_bytes())
    assert report["status"] == "incomplete"
    assert (
        len(report["planned_scenario_ids"])
        == len(report["offline_bands"]["cases"])
        == 25
    )
    assert len(report["results"]) == 10
    assert states[0]["round"]["status"] == states[1]["round"]["status"] == "completed"
    assert (
        len(json.loads((output / "private-access.json").read_bytes())["players"]) == 25
    )
    assert len(controls["logouts"]) == 16


def test_unavailable_ui_prevents_creating_any_game(fake_games):
    run, states, controls, _ = fake_games
    controls["bad_ui"] = 3
    with pytest.raises(ValueError, match="UI is not ready"):
        run()
    assert all(s["round"] is None and not s["players"] for s in states)
