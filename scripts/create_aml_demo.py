"""Publish all frozen AML cases to five fresh, isolated local game instances.

Requires an accepted production package and the exact demo frozen before its
training. Credentials come from AML_DEMO_ADMIN_EMAIL / AML_DEMO_ADMIN_PASSWORD.
Partial failures preserve private access and a journal; existing games are never
restarted or deleted. This command does not certify browser or restore checks.
"""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from html import escape
import json
import math
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from scripts.aml_dataset.aml_training import audit_dataset, check, json_bytes
from scripts.aml_demo_casebook import ROOT, evaluate_bands, validate_roster
from scripts.aml_demo_training import verify_frozen_demo
from src.aml_workshop_simulator.schemas.round_config import AMLGameConfigIn
from src.aml_workshop_simulator.schemas.leaderboard import ResultOut
from src.aml_workshop_simulator.schemas.game_state import ResourceSnapshotOut
from src.aml_workshop_simulator.schemas.scoring import AMLProbabilityExplanationOut
from src.aml_workshop_simulator.services.aml_context import evaluate
from src.aml_workshop_simulator.domain.scoring import (
    resource_score,
    probability_leaderboard_scores,
)
from src.aml_workshop_simulator.services.aml_dataset_features_v5 import extract_features
from src.aml_workshop_simulator.services.aml_probability_model import (
    AMLProbabilityModel,
    canonical_hash,
)


def validate_targets(api_urls, ui_urls):
    check(len(api_urls) == len(ui_urls) == 5, "Five isolated API/UI pairs required")

    def origin(value):
        parsed = urlsplit(value)
        check(
            parsed.scheme in {"http", "https"}
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and parsed.path in {"", "/"},
            "Expected a local application origin without path or credentials",
        )
        # localhost/127.0.0.1/::1 aliases cannot manufacture independent targets.
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return value.rstrip("/"), (parsed.scheme, port)

    apis, uis = [origin(v) for v in api_urls], [origin(v) for v in ui_urls]
    check(
        len({key for _, key in apis}) == len({key for _, key in uis}) == 5,
        "Targets must be distinct",
    )
    check(
        not {key for _, key in apis} & {key for _, key in uis},
        "API and UI targets must be distinct",
    )
    return [{"api_url": a[0], "ui_url": u[0]} for a, u in zip(apis, uis, strict=True)]


def input_config(config):
    return AMLGameConfigIn.model_validate(
        {
            k: v
            for k, v in config.items()
            if k not in {"card_snapshots", "risk_model", "config_version"}
        }
    ).dump()


def server_steps(public, saved):
    """Translate database primary keys only; reject every economic change."""
    check(
        input_config(public["config"]) == input_config(saved),
        "Server config differs from frozen context",
    )

    def cards(config):
        values = config["card_snapshots"]
        by_key = {(c["code"], c["version"]): c for c in values}
        check(len(by_key) == len(values), "Duplicate server card version")
        return by_key

    original, actual = cards(public["config"]), cards(saved)
    check(original.keys() == actual.keys(), "Server card roster changed")
    for key in original:
        check(
            {k: v for k, v in original[key].items() if k != "id"}
            == {k: v for k, v in actual[key].items() if k != "id"},
            "Server card semantics changed",
        )
    steps = deepcopy(public["steps"])
    for step in steps:
        step["card"]["id"] = actual[(step["card"]["code"], step["card"]["version"])][
            "id"
        ]
    check(
        extract_features(steps=steps, config=saved) == extract_features(**public),
        "Transport changed model features",
    )
    return steps


def server_explanation(expected, frozen_config, saved):
    """Bind identical predictions to the API's validated JSON representation.

    Pydantic materializes optional history fields as null. This changes the raw
    context hash even though the input config and extracted features are equal.
    Preserve every prediction field and verify both contexts before rebinding.
    """
    check(input_config(frozen_config) == input_config(saved), "Server context changed")
    check(
        expected["context_sha256"] == canonical_hash(frozen_config["behavior"]),
        "Offline prediction belongs to another frozen context",
    )
    result = deepcopy(expected)
    result["context_sha256"] = canonical_hash(saved["behavior"])
    return result


class Api:
    def __init__(self, client):
        self.client = client

    def call(self, method, path, *, token=None, payload=None):
        try:
            response = self.client.request(
                method,
                path,
                json=payload,
                headers={"X-Session-ID": token} if token else {},
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"API transport failure: {method} {path} ({type(exc).__name__})"
            ) from None
        if not 200 <= response.status_code < 300:
            # Response bodies may contain submitted credentials or session IDs.
            raise RuntimeError(
                f"API command failed: {method} {path}, HTTP {response.status_code}"
            )
        return None if response.status_code == 204 else response.json()


def load_inputs(dataset, package, casebook):
    dataset, package, casebook = map(Path, (dataset, package, casebook))
    model = AMLProbabilityModel(package)  # Deliberately no offline-candidate override.
    audit = audit_dataset(dataset)
    check(
        audit["release_ready"] and not audit["unmet_gates"], "Accepted dataset required"
    )
    check(
        sha256((dataset / "manifest.json").read_bytes()).hexdigest()
        == model.manifest["dataset_manifest_sha256"],
        "Model belongs to another dataset",
    )
    binding, snapshot = verify_frozen_demo(casebook, dataset / "casebook.jsonl")
    training_raw = (package / "training-manifest.json").read_bytes()
    check(
        sha256(training_raw).hexdigest()
        == model.manifest["artifact_hashes"]["training-manifest.json"],
        "Training manifest changed after package load",
    )
    training = json.loads(training_raw)
    check(
        training["artifact_hashes"].get("demo-freeze/manifest.json")
        == binding["freeze_manifest_sha256"],
        "Demo was not bound before this model's training",
    )
    value = json.loads(snapshot["casebook.json"])
    for row in validate_roster(value):
        model.check_config(row["public_snapshot"]["config"])
    return model, value, binding


def write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(json_bytes(value))
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def pin(model, config):
    return dict(
        model.model_identity,
        score_kind="aml_probability",
        explanation_version=4,
        model_version="aml-probability:sha256:"
        + model.model_identity["package_sha256"],
        context_sha256=canonical_hash(config["behavior"]),
    )


def check_result(result, expected, *, scenario_id, steps, config):
    check(isinstance(result, dict), "Missing stored result")
    result = ResultOut.model_validate(result).model_dump(mode="json")
    check(
        result["scenario_id"] == scenario_id, "Stored result scenario identity mismatch"
    )
    resources = ResourceSnapshotOut.model_validate(evaluate(steps, config)).model_dump(
        mode="json"
    )
    # JSONB object-key ordering can reorder named quota limits on evaluation;
    # their values matter, while transaction/timeline order remains exact.
    for snapshot in (resources, result["resources"]):
        snapshot["limits"] = sorted(snapshot["limits"], key=lambda item: item["code"])
    check(
        result["resources"] == resources, "Stored resources differ from offline engine"
    )
    scores = probability_leaderboard_scores(
        expected["aml_probability"], resource_score(resources, config), config
    )
    scores["risk_score"] = (Decimal(str(expected["aml_probability"])) * 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    for key, value in scores.items():
        check(
            Decimal(result["scores"][key]) == value,
            f"Stored {key} differs from offline",
        )
    check(
        result["scores"]["risk_label"]
        == {"low": "normal", "review": "review", "high": "suspicious"}[
            expected["category"]
        ],
        "Stored risk label differs from offline",
    )
    expected = AMLProbabilityExplanationOut.model_validate(expected).model_dump(
        mode="json"
    )
    actual = AMLProbabilityExplanationOut.model_validate(
        result["explanation"]
    ).model_dump(mode="json")
    for key in (
        "model_identity",
        "context_sha256",
        "category",
        "calibration",
        "context_status",
    ):
        check(actual[key] == expected[key], f"Stored result {key} differs from offline")
    for key in (
        "aml_probability",
        "uncalibrated_probability",
        "raw_margin",
        "base_margin",
    ):
        check(
            math.isclose(actual[key], expected[key], rel_tol=0, abs_tol=1e-8),
            f"Stored result {key} differs from offline",
        )
    check(
        abs(
            actual["base_margin"]
            + sum(v["contribution"] for v in actual["shap_values"])
            - actual["raw_margin"]
        )
        <= 1e-6,
        "Stored SHAP does not reconstruct margin",
    )
    check(
        [v["feature"] for v in actual["shap_values"]]
        == [v["feature"] for v in expected["shap_values"]],
        "Stored SHAP roster differs from offline",
    )
    for a, b in zip(actual["shap_values"], expected["shap_values"], strict=True):
        check(
            a["value"] == b["value"]
            and math.isclose(
                a["contribution"], b["contribution"], rel_tol=0, abs_tol=1e-6
            ),
            "Stored SHAP differs from offline",
        )
    return actual["aml_probability"]


def write_index(output, report):
    rows = []
    for game in report["rounds"]:
        rows.append(
            "<tr><td>"
            + escape(game["title"])
            + '</td><td><a href="'
            + escape(game["ui_url"] + "/play/login", quote=True)
            + '">Игрок</a></td><td><a href="'
            + escape(game["ui_url"] + "/admin/login", quote=True)
            + '">Организатор</a></td></tr>'
        )
    cases = []
    for case in report.get("bands", {}).get("cases", []):
        cases.append(
            "<tr><td>"
            + escape(case["scenario_id"])
            + "</td><td>"
            + escape(case["expected_band"])
            + "</td><td>"
            + format(case["aml_probability"], ".6f")
            + "</td><td>"
            + escape(str(case["band_passed"]))
            + "</td></tr>"
        )
    html = (
        '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Пять AML-демоигр</title>'
        "<style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px}table{border-collapse:collapse;width:100%;margin:24px 0}td,th{padding:10px;border-bottom:1px solid #ccc;text-align:left}a{color:#1757ad}</style>"
        "<h1>Пять AML-демоигр</h1><p>Состояние: "
        + escape(report["status"])
        + ". Учётные данные хранятся отдельно в private-access.json.</p><table><tr><th>Игра</th><th>Вход игрока</th><th>Вход организатора</th></tr>"
        + "".join(rows)
        + '</table><p><a href="report.json">Полный отчёт: все цепочки, контексты и результаты</a></p>'
        + "<table><tr><th>Цепочка</th><th>Ожидаемый диапазон</th><th>p</th><th>Соответствие</th></tr>"
        + "".join(cases)
        + "</table></html>"
    )
    (output / "index.html").write_text(html, encoding="utf-8")


def create_demo(*, dataset, package, casebook, api_urls, ui_urls, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Refusing existing demo output")
    check(
        output.resolve().is_relative_to((ROOT / ".local-run").resolve()),
        "Private output must be under .local-run",
    )
    targets = validate_targets(api_urls, ui_urls)
    email, password = (
        os.environ.get("AML_DEMO_ADMIN_EMAIL"),
        os.environ.get("AML_DEMO_ADMIN_PASSWORD"),
    )
    check(
        bool(email) and bool(password), "Organizer credentials required in environment"
    )
    model, value, binding = load_inputs(dataset, package, casebook)
    rows = validate_roster(value)
    expected = {r["scenario_id"]: model.predict(**r["public_snapshot"]) for r in rows}
    for result in expected.values():
        AMLProbabilityExplanationOut.model_validate(result)
    run_id = uuid4().hex[:12]
    access = {
        "run_id": run_id,
        "organizer": {"email": email, "password": password},
        "players": [],
    }
    by_sid = {}
    for i, row in enumerate(rows, 1):
        entry = {
            "scenario_id": row["scenario_id"],
            "email": f"aml-{run_id}-{i:02d}@example.com",
            "display_name": f"Участник {i:02d}",
            "password": secrets.token_urlsafe(24),
            "client_mutation_id": str(uuid4()),
        }
        access["players"].append(entry)
        by_sid[row["scenario_id"]] = entry
    report = {
        "scope": "five-isolated-demo-api-and-bands-only",
        "release_ready": False,
        "run_id": run_id,
        "status": "in-progress",
        "binding": binding,
        "model_identity": model.model_identity,
        "rounds": [
            {**target, "round_key": game["round_key"], "title": game["title"]}
            for target, game in zip(targets, value["rounds"], strict=True)
        ],
        "planned_scenario_ids": [r["scenario_id"] for r in rows],
        "results": {},
        "offline_bands": evaluate_bands(
            value, {sid: item["aml_probability"] for sid, item in expected.items()}
        ),
        "phase": "preflight",
    }
    output.mkdir(parents=True, mode=0o700)
    write_json(output / "private-access.json", access)

    def checkpoint(phase):
        report["phase"] = phase
        write_json(output / "report.json", report)
        write_index(output, report)

    checkpoint("preflight")

    def logout(api, token):
        try:
            api.call("DELETE", "auth/session", token=token)
        except (RuntimeError, ValueError):
            report["logout_failures"] = report.get("logout_failures", 0) + 1

    try:
        with ExitStack() as stack:
            apps = []
            for target in targets:
                client = stack.enter_context(
                    httpx.Client(
                        base_url=target["api_url"] + "/api/v1/",
                        timeout=180,
                        follow_redirects=False,
                        trust_env=False,
                    )
                )
                api = Api(client)
                try:
                    ui_ready = client.get(target["ui_url"] + "/health/live")
                except httpx.HTTPError:
                    raise RuntimeError("Demo UI health check failed") from None
                check(ui_ready.status_code == 200, "Demo UI is not ready")
                login = api.call(
                    "POST",
                    "auth/login",
                    payload={"email": email, "password": password, "audience": "admin"},
                )
                check(
                    login["user"]["role"] == "admin" and login["audience"] == "admin",
                    "Organizer login required",
                )
                token = login["session_id"]
                stack.callback(logout, api, token)
                check(
                    api.call("GET", "admin/rounds/current", token=token) is None,
                    "Target already contains a game",
                )
                apps.append((api, token))
            for game, live, (api, admin) in zip(
                value["rounds"], report["rounds"], apps, strict=True
            ):
                checkpoint("create:" + game["round_key"])
                check(
                    api.call("GET", "admin/rounds/current", token=admin) is None,
                    "Targets share an existing game",
                )
                public = game["cases"][0]["record"]["public_snapshot"]
                created = api.call(
                    "POST",
                    "admin/rounds",
                    token=admin,
                    payload={
                        "title": game["title"],
                        "game_config": input_config(public["config"]),
                    },
                )
                rid = created["id"]
                live["round_id"] = rid
                saved = created["game_config"]
                check(
                    saved.get("risk_model") == pin(model, saved),
                    "API pinned a different model/context",
                )
                submissions = {
                    c["record"]["scenario_id"]: server_steps(
                        c["record"]["public_snapshot"], saved
                    )
                    for c in game["cases"]
                }
                transported = {
                    c["record"]["scenario_id"]: server_explanation(
                        expected[c["record"]["scenario_id"]],
                        c["record"]["public_snapshot"]["config"],
                        saved,
                    )
                    for c in game["cases"]
                }
                live["frozen_context_sha256"] = canonical_hash(
                    public["config"]["behavior"]
                )
                live["stored_context_sha256"] = canonical_hash(saved["behavior"])
                started = api.call("POST", f"admin/rounds/{rid}/start", token=admin)
                check(
                    started["status"] == "active" and started["game_config"] == saved,
                    "Started context changed",
                )
                players = []
                for case in game["cases"]:
                    sid = case["record"]["scenario_id"]
                    entry = by_sid[sid]
                    entry.update(
                        round_key=game["round_key"], ui_url=live["ui_url"], round_id=rid
                    )
                    write_json(output / "private-access.json", access)
                    checkpoint("register-submit:" + sid)
                    registered = api.call(
                        "POST",
                        "auth/register",
                        payload={
                            k: entry[k] for k in ("email", "password", "display_name")
                        },
                    )
                    login = api.call(
                        "POST",
                        "auth/login",
                        payload={
                            "email": entry["email"],
                            "password": entry["password"],
                            "audience": "play",
                        },
                    )
                    check(
                        login["user"]["id"] == registered["id"]
                        and login["user"]["role"] == "participant"
                        and login["audience"] == "play",
                        "Player login identity mismatch",
                    )
                    token = login["session_id"]
                    stack.callback(logout, api, token)
                    submitted = api.call(
                        "POST",
                        f"rounds/{rid}/scenario/submit",
                        token=token,
                        payload={
                            "steps": submissions[sid],
                            "expected_revision": 0,
                            "client_mutation_id": entry["client_mutation_id"],
                        },
                    )
                    check(submitted["status"] == "submitted", "Scenario not submitted")
                    check(
                        submitted["round_id"] == rid
                        and submitted["participant_id"] == registered["id"],
                        "Submitted scenario identity mismatch",
                    )
                    entry.update(
                        participant_id=registered["id"],
                        server_scenario_id=submitted["id"],
                    )
                    write_json(output / "private-access.json", access)
                    players.append((sid, entry, token))
                checkpoint("score:" + game["round_key"])
                summary = api.call("POST", f"admin/rounds/{rid}/score", token=admin)
                check(
                    summary["status"] == "completed"
                    and summary["submitted_count"] == summary["scored_count"] == 5,
                    "Incomplete five-player scoring",
                )
                check(
                    api.call("POST", f"admin/rounds/{rid}/score", token=admin)
                    == summary,
                    "Scoring retry changed summary",
                )
                for sid, entry, token in players:
                    result = api.call("GET", f"rounds/{rid}/result", token=token)
                    probability = check_result(
                        result,
                        transported[sid],
                        scenario_id=entry["server_scenario_id"],
                        steps=submissions[sid],
                        config=saved,
                    )
                    check(
                        api.call("GET", f"rounds/{rid}/result", token=token) == result,
                        "Stored result changed on repeat read",
                    )
                    report["results"][sid] = {
                        "aml_probability": probability,
                        "result": result,
                        "round_key": game["round_key"],
                        "display_name": entry["display_name"],
                    }
                admin_board = api.call(
                    "GET", f"admin/rounds/{rid}/leaderboard", token=admin
                )["rows"]
                check(
                    {r["email"] for r in admin_board}
                    == {entry["email"] for _, entry, _ in players}
                    and len(admin_board) == 5,
                    "Organizer board roster mismatch",
                )
                expected_board = {
                    entry["display_name"]: expected[sid]["aml_probability"]
                    for sid, entry, _ in players
                }
                for board in [admin_board] + [
                    api.call("GET", f"rounds/{rid}/leaderboard", token=token)["rows"]
                    for _, _, token in players
                ]:
                    check(
                        len(board) == 5
                        and {r["display_name"] for r in board} == set(expected_board),
                        "Game boards are not isolated",
                    )
                    for row in board:
                        check(
                            row["score_kind"] == "aml_probability"
                            and math.isclose(
                                row["aml_probability"],
                                expected_board[row["display_name"]],
                                abs_tol=1e-8,
                                rel_tol=0,
                            ),
                            "Board probability mismatch",
                        )
                live["summary"] = summary
                checkpoint("completed:" + game["round_key"])
            for game, (api, admin) in zip(report["rounds"], apps, strict=True):
                current = api.call("GET", "admin/rounds/current", token=admin)
                check(
                    current["id"] == game["round_id"]
                    and current["status"] == "completed",
                    "Demo game was replaced",
                )
            report["bands"] = evaluate_bands(
                value,
                {sid: r["aml_probability"] for sid, r in report["results"].items()},
            )
            report["status"] = (
                "completed"
                if report["bands"]["bands_passed"]
                else "completed-with-band-failures"
            )
            checkpoint("finished")
        checkpoint(report["phase"])
    except Exception as exc:
        report["status"] = "incomplete"
        report["failure_type"] = type(exc).__name__
        checkpoint(report["phase"])
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "package", "casebook", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--api-url",
        action="append",
        required=True,
        help="Five fresh API origins, in frozen round order",
    )
    parser.add_argument(
        "--ui-url", action="append", required=True, help="Five matching UI origins"
    )
    args = parser.parse_args()
    try:
        report = create_demo(
            dataset=args.dataset,
            package=args.package,
            casebook=args.casebook,
            output=args.output,
            api_urls=args.api_url,
            ui_urls=args.ui_url,
        )
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        parser.exit(
            1,
            f"Demo incomplete ({type(exc).__name__}); inspect private output journal.\n",
        )
    print(args.output / "index.html")
    if not report["bands"]["bands_passed"]:
        parser.exit(
            2,
            "All games created; some frozen expected bands failed. All cases retained.\n",
        )


if __name__ == "__main__":
    main()
