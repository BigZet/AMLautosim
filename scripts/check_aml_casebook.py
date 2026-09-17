"""Structural/financial feasibility audit; no label inference or human review."""
import argparse
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from src.aml_workshop_simulator.core.errors import ValidationFailed
from scripts.aml_dataset.aml_labels import validate_label, validate_public
from src.aml_workshop_simulator.services.aml_context import evaluate
from src.aml_workshop_simulator.domain.simulation import submit_blockers

def audit_casebook(casebook: Path, protocol: Path) -> dict:
    rules = json.loads(Path(protocol).read_text(encoding="utf-8"))
    errors, rows, ids = [], [], set()
    status, reviews, families = Counter(), Counter(), Counter()
    for line_number, line in enumerate(Path(casebook).read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
            validate_label(row)
            validate_public(row["public_snapshot"])
            if row["scenario_id"] in ids:
                raise ValueError("duplicate scenario_id")
            ids.add(row["scenario_id"])
            if row["family_id"] not in rules["families"]:
                raise ValueError("unsupported family_id")
            for key in ("author_truth", "hypothesis_source", "alternative_explanation", "necessary_facts", "forbidden_information", "observability"):
                if not row.get(key):
                    raise ValueError(f"missing {key}")
            if row["label_status"] == "confirmed" and row["author_truth"].get("aml_episode_present") is not bool(row["aml_label"]):
                raise ValueError("truth/label mismatch")
            public = row["public_snapshot"]
            config = deepcopy(public["config"])
            steps = deepcopy(public["steps"])
            blockers = submit_blockers(evaluate(steps, config))
            if blockers:
                raise ValueError(f"resource blockers: {blockers}")
            category = "unresolved" if row["aml_label"] is None else f"confirmed_{row['aml_label']}"
            status[category] += 1
            reviews[row["review_status"]] += 1
            families[(row["family_id"], category)] += 1
            rows.append(row)
        except (ValueError, KeyError, TypeError, ValidationFailed) as exc:
            errors.append({"line": line_number, "error": str(exc)})
    for family in rules["families"]:
        for category in ("confirmed_0", "confirmed_1", "unresolved"):
            if families[(family, category)] != 4:
                errors.append({"family": family, "status": category, "error": "pilot requires four cases per family/status"})
    return {"case_count": len(rows), "errors": errors, "status_counts": dict(status), "review_counts": dict(reviews),
            "release_eligible": False, "financial_contract": "v10", "v10_verification": "passed" if not errors else "failed",
            "indistinguishability": [{"scenario_id": r["scenario_id"], "reason": r["observability"]["reason"]} for r in rows if not r["observability"]["distinguishable"]]}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--casebook", type=Path, default=Path("resources/aml_dataset/aml-v1/pilot/casebook.jsonl"))
    parser.add_argument("--protocol", type=Path, default=Path("config/ml/aml-classifier-v1-protocol.json"))
    args = parser.parse_args()
    report = audit_casebook(args.casebook, args.protocol)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(bool(report["errors"]))

if __name__ == "__main__":
    main()
