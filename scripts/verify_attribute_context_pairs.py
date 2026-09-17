"""Validate learned contextual sensitivity and expected neutral transformations."""

from copy import deepcopy
import json
from pathlib import Path
from scripts.aml_attribute_label_policy import assess_panel
from src.aml_workshop_simulator.services.game_classifier import GameClassifier
from src.aml_workshop_simulator.services.aml_game_attribute_features_v1 import (
    extract_panel_features,
)


def run(package, output):
    model = GameClassifier(package)
    # Use real card identifiers and canonical v10 fields; scorer independently validates.
    cards = {c["code"]: c for c in model.context["card_snapshots"]}
    steps = []
    for i in range(3):
        for code, amount, party in [
            ("incoming_transfer", "100000", "A"),
            ("card_transfer", "88000", "BCD"[i]),
        ]:
            s = dict(
                step_id=f"00000000-0000-4000-8000-{len(steps) + 1:012d}",
                card={k: cards[code][k] for k in ("id", "code", "version")},
                amount=amount,
                purpose_code="unknown",
                claim_id=None,
                interval_minutes=None
                if not steps
                else 1
                if code == "card_transfer"
                else 60,
                context={
                    "channel": "bank" if code == "incoming_transfer" else "mobile"
                },
                action_details={"incoming_kind": "bank_transfer", "bank_country": "RU"}
                if code == "incoming_transfer"
                else {},
            )
            s["sender_id" if code == "incoming_transfer" else "recipient_id"] = party
            steps.append(s)
    config = {**model.context, "risk_model": model.identity}

    def evaluate(s):
        return dict(
            target=assess_panel(extract_panel_features(s))["target_probability"],
            prediction=model.predict(s, config, explain=False),
        )

    baseline = evaluate(steps)
    cases = {}
    for key in (
        "channel",
        "country",
        "kind",
        "purpose",
        "neutral_country",
        "neutral_channel",
    ):
        s = deepcopy(steps)
        if key == "channel":
            s[3]["context"]["channel"] = "web"
        if key == "country":
            s[2]["action_details"]["bank_country"] = "KG"
        if key == "kind":
            s[2]["action_details"] = {"incoming_kind": "payment_service"}
        if key == "purpose":
            s[3]["purpose_code"] = "refund"
        if key == "neutral_country":
            for x in s[::2]:
                x["action_details"]["bank_country"] = "KG"
        if key == "neutral_channel":
            for x in s[1::2]:
                x["context"]["channel"] = "branch"
        result = evaluate(s)
        if key.startswith("neutral"):
            assert result == baseline, (key, result, baseline)
        else:
            assert result["target"] > baseline["target"]
            assert result["prediction"] > baseline["prediction"] + 0.001, (
                key,
                result,
                baseline,
            )
            assert abs(result["prediction"] - result["target"]) < 0.06
        cases[key] = result
    report = dict(
        passed=True,
        baseline=baseline,
        cases=cases,
        identity=model.identity,
        scope="Controlled canonical input pairs isolate scoring, not full round resource feasibility",
    )
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("package", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    run(a.package, a.output)
