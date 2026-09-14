"""Build a local, offline review page. Never supplies human judgments."""

import argparse
import json
from pathlib import Path

from src.aml_workshop_simulator.domain.operation_timeline import operation_timeline
from scripts.aml_dataset.mass_release import review_contract


def project_case(row, blind=False, reason=""):
    config = row["config_snapshot"]
    result = {key: row[key] for key in ("id", "observable_hash", "steps", "resources", "totals")}
    result.update(
        behavior=config["behavior"], initial_resources=config["resources"],
        timeline=operation_timeline(row["steps"], config["behavior"]["timeline"]),
        selection=reason,
    )
    if not blind:
        result["target"] = row["target_risk_score"]
        result["explanation"] = row["explanation"]
    return result


def build_page(pilot, reference, output):
    pilot, reference, output = map(Path, (pilot, reference, output))
    manifest = json.loads((pilot / "manifest.json").read_text())
    ref_manifest = json.loads((reference / "manifest.json").read_text())
    if manifest["stage"] != "pilot" or manifest["reference_package_hash"] != ref_manifest["package_hash"]:
        raise ValueError("Pilot and reference packages do not match")
    contract = review_contract(pilot)
    sample = [json.loads(s) for s in (pilot / contract["sample"]).read_text().splitlines()]
    blind = ([json.loads(s) for s in (reference / "challenges.jsonl").read_text().splitlines()]
             if contract["blind"] else [])
    payload = dict(
        key=manifest["rows_hash"] + ":" + ref_manifest["package_hash"] + ":" + contract["sample"],
        decisions_filename=contract["decisions"],
        pilot=[project_case(r["record"], reason=r["reason"]) for r in sample],
        blind=[project_case(r, blind=True) for r in blind],
    )
    # Data is inserted into a JSON script element, never interpolated as HTML.
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    template = Path(__file__).with_name("aml_dataset").joinpath(
        "review_ui.html" if contract["blind"] else "review_ui_short.html"
    ).read_text()
    output.write_text(template.replace("__REVIEW_DATA__", data))
    return {"pilot_cases": len(sample), "blind_cases": len(blind), "output": str(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--pilot", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(build_page(args.pilot, args.reference, args.output))
