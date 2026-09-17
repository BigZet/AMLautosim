"""Measure all authored coverage axes before selecting the main population."""

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from scripts.aml_dataset import aml_population_author as population
from scripts.aml_dataset.aml_population_rails import (
    author_route,
    compile_route,
    compile_inactive_history,
)


def build(selection, output):
    selection, output = Path(selection), Path(output)
    if output.exists():
        raise FileExistsError(output)
    raw = (selection / "selected-worlds.jsonl").read_bytes()
    representatives = {}
    for line in raw.splitlines():
        world = population.world_from_dict(json.loads(line))
        key = (world.source, world.profile["id"])
        representatives.setdefault(key, world)
    sources = population.compiler_hashes()
    for name in (
        "scripts/build_aml_coverage_probe.py",
        "scripts/aml_dataset/aml_population_rails.py",
    ):
        sources[name] = sha256(Path(name).read_bytes()).hexdigest()
    rows, dossiers = [], []
    for world in representatives.values():
        rows.extend(population.compile_variants(world, 0))
        rows.extend(population.compile_diagnostics(world))
        rows.extend(
            r for r in population.graph.compile_root(world) if r["aml_label"] is None
        )
        for kind in ("cash", "salary_purchase"):
            dossier = population.author_coverage_case(world, kind)
            dossiers.append(dossier)
            rows.extend(population.compile_coverage_case(dossier))
        for rail in (
            ("payment_service", "crypto_p2p", "exchange_withdrawal")
            if world.source == "asset"
            else ("payment_service",)
        ):
            dossier = author_route(world, rail)
            dossiers.append(dossier)
            rows.extend(compile_route(dossier))
        rows.extend(compile_inactive_history(world))
    features = population.validate_sources(rows, population.protocol())
    closure = population.connected_groups(rows, features)
    artifacts = {
        "roots.jsonl": population.jsonl_bytes(
            [asdict(w) for w in representatives.values()]
        ),
        "dossiers.jsonl": population.jsonl_bytes(dossiers),
        "casebook.jsonl": population.jsonl_bytes(rows),
        "features.json": population.json_bytes(features),
        "provenance.json": population.json_bytes(closure),
    }
    report = dict(
        scope="all-coverage-axes-pilot-not-main-selection",
        rows=len(rows),
        roots=len(representatives),
        components=len(closure["groups"]),
        coverage=population.coverage_report(
            [r for r in rows if r["aml_label"] is not None], population.protocol()
        ),
        input_sha256=sha256(raw).hexdigest(),
        source_hashes=sources,
        artifact_hashes={
            name: sha256(data).hexdigest() for name, data in artifacts.items()
        },
        release_ready=False,
        reviewed_rows=0,
        remaining="Independent domain review and full retained-universe closure; no claims of test support or 1200 main groups",
    )
    output.mkdir(parents=True)
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
    (output / "audit.json").write_bytes(population.json_bytes(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build(args.selection, args.output)
    print(
        json.dumps(
            {k: report[k] for k in ("rows", "roots", "components", "release_ready")}
        )
    )
    print(json.dumps({"missing_cells": report["coverage"]["missing_cells"]}))
