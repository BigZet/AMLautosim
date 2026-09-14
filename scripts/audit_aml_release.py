"""Summarize a validated synthetic release and compare its reproducible pilot prefix."""

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


def audit(release, pilot):
    release, pilot = Path(release), Path(pilot)
    pilot_lines = (pilot / "scenarios.jsonl").read_text().splitlines()
    scores, salaries, purchases, turnovers, parents = [], Counter(), Counter(), set(), Counter()
    unique = set()
    with (release / "scenarios.jsonl").open() as f:
        for index, line in enumerate(f):
            if index < len(pilot_lines) and line.rstrip("\n") != pilot_lines[index]:
                raise ValueError("Release prefix does not reproduce the independent pilot run")
            row = json.loads(line)
            if row["observable_hash"] in unique:
                raise ValueError("Duplicate observable hash")
            unique.add(row["observable_hash"])
            scores.append(row["target_risk_score"])
            salaries[row["features"]["income_basis"]] += 1
            purchases[row["features"]["count_purchase"]] += 1
            turnovers.add(row["features"]["target_outflow"])
            parents[row["group"]] += 1
    scores.sort()
    split = Counter(r["split"] for r in csv.DictReader((release / "split.csv").open()))
    report = dict(
        count=len(scores), unique_observations=len(unique), pilot_prefix_reproduced=len(pilot_lines),
        split=dict(split), parent_groups=dict(parents), salary_basis=dict(salaries), purchases=dict(purchases),
        turnovers=sorted(turnovers),
        risk_quantiles={str(q): scores[round((len(scores)-1)*q)] for q in (0,.25,.5,.75,1)},
        risk_bands=dict(Counter(str(min(3, int(score // 25))) for score in scores)),
        independent_blind_evaluation=False,
    )
    (release / "AUDIT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    hashes = {}
    for name in ("scenarios.jsonl", "features.csv", "split.csv", "configurations.json",
                 "rubric.json", "manifest.json", "feature-schema.json", "quality.json", "AUDIT.json"):
        h = hashlib.sha256()
        with (release / name).open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        hashes[name] = h.hexdigest()
    (release / "CHECKSUMS.json").write_text(json.dumps(hashes, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--release", required=True)
    parser.add_argument("--pilot", required=True)
    args = parser.parse_args()
    print(audit(args.release, args.pilot))
