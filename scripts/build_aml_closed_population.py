"""Compile a uniform, unreviewed population with four bounded CPU workers."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
from pathlib import Path

from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_population_rails import author_route, compile_route
from scripts.audit_aml_history_population import file_hash, require


def compile_unit(task):
    raw, selection = task
    world = p.world_from_dict(raw)
    p.validate_role_world(world)
    require(
        world.id == selection["root_id"]
        and world.profile["id"] == selection["profile"]
        and p.digest(world.activity) == selection["activity_sha256"],
        "Selected world binding mismatch",
    )
    rows = (
        p.compile_probe_rows(world)
        + p.compile_variants(world, selection["extra_label"])
        + p.compile_diagnostics(world)
    )
    rows += [r for r in p.graph.compile_root(world) if r["aml_label"] is None]
    kinds, rails = selection.get("coverage_kinds", []), selection.get("rails", [])
    require(kinds in ([], ["cash", "salary_purchase"]), "Unsupported coverage policy")
    require(
        rails
        in (
            [],
            ["payment_service"],
            ["payment_service", "crypto_p2p", "exchange_withdrawal"],
        ),
        "Unsupported rail policy",
    )
    for kind in kinds:
        rows += p.compile_coverage_case(p.author_coverage_case(world, kind))
    for rail in rails:
        rows += compile_route(author_route(world, rail))
    recipes = {f"schedule-{schedule}-{mode}" for schedule, mode in p.RECIPES}
    if kinds:
        recipes -= {"schedule-1-records", "schedule-1-wrong_cover"}
        recipes |= {"coverage-cash", "coverage-salary_purchase"}
    if rails:
        recipes -= {"schedule-2-sources", "schedule-2-obligations"}
        recipes |= {"rail-payment_service-records", "rail-payment_service-obligations"}
    if "crypto_p2p" in rails:
        recipes -= {"schedule-1-obligations", "schedule-2-wrong_cover"}
        recipes |= {"rail-crypto_p2p-records", "rail-exchange_withdrawal-records"}
    main_ids = []
    for row in rows:
        row["provenance"]["parent_ids"] = sorted(
            set(row["provenance"].get("parent_ids", [])) | set(selection["parent_ids"])
        )
        if (
            row["variant_recipe"] in recipes
            or row["variant_recipe"] == "schedule-0-records-opening-unverified"
        ):
            row["population_role"] = "selected_main_draft"
            main_ids.append(row["scenario_id"])
        else:
            row["population_role"] = "retained_auxiliary_draft"
    require(len(main_ids) == 25, "Uniform main recipe count mismatch")
    counts = Counter(r["aml_label"] for r in rows if r["scenario_id"] in main_ids)
    require(sorted(counts.values()) == [12, 13], "Main unit label balance mismatch")
    features = p.validate_sources(rows, p.protocol())
    return rows, main_ids, features


def build(selection, output, workers=4):
    selection, output = Path(selection), Path(output)
    require(not output.exists(), "Population output already exists")
    receipt = json.loads((selection / "audit.json").read_bytes())
    require(
        receipt["selected_components"] == 1200
        and receipt["planned_main_rows"] == 30000,
        "Population selection size mismatch",
    )
    for name, expected in receipt["source_hashes"].items():
        require(file_hash(name) == expected, "Selection source drift: " + name)
    for name, expected in receipt["artifact_hashes"].items():
        require(file_hash(selection / name) == expected, "Selection artifact mismatch")
    worlds = [
        json.loads(line)
        for line in (selection / "selected-worlds.jsonl").read_bytes().splitlines()
    ]
    items = json.loads((selection / "selections.json").read_bytes())
    require(len(worlds) == len(items) == 1200, "Selection roster mismatch")
    require(
        len({s["raw_component"] for s in items}) == 1200, "Repeated selected component"
    )
    sources = {
        **p.compiler_hashes(),
        "scripts/aml_dataset/aml_population_rails.py": file_hash(
            "scripts/aml_dataset/aml_population_rails.py"
        ),
        "scripts/build_aml_closed_population.py": file_hash(__file__),
    }
    output.mkdir(parents=True)
    policy = dict(
        scope="uniform-draft-population-before-model-access",
        selection_receipt_sha256=file_hash(selection / "audit.json"),
        main_rows=30000,
        variants_per_selected_component=25,
        unavailable_main_pairs_per_unit=2,
        channel_policy="Both truths for bank, cash, payroll, payment service; actual asset-sale units also P2P and exchange",
        source_hashes=sources,
        reviewed_rows=0,
        release_ready=False,
    )
    (output / "prefit-policy.json").write_bytes(p.json_bytes(policy))
    vectors, closure, labels, main_total, main_ids_all = {}, [], Counter(), 0, []
    digests = {name: sha256() for name in ("casebook.jsonl", "main.jsonl")}
    handles = {name: (output / name).open("xb") for name in digests}
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for index, (rows, main_ids, features) in enumerate(
                pool.map(compile_unit, zip(worlds, items, strict=True)), 1
            ):
                require(
                    not vectors.keys() & features.keys(), "Duplicate scenario identity"
                )
                vectors.update(features)
                closure.extend(p.closure_row(row) for row in rows)
                main = [r for r in rows if r["scenario_id"] in main_ids]
                labels.update(r["aml_label"] for r in main)
                main_total += len(main)
                main_ids_all.extend(main_ids)
                for name, records in (("casebook.jsonl", rows), ("main.jsonl", main)):
                    data = p.jsonl_bytes(records)
                    handles[name].write(data)
                    digests[name].update(data)
                if index % 50 == 0:
                    progress = dict(
                        worlds=index,
                        main_rows=main_total,
                        all_rows=len(closure),
                        release_ready=False,
                    )
                    (output / "progress.json").write_bytes(p.json_bytes(progress))
                    print(json.dumps(progress), flush=True)
    finally:
        for handle in handles.values():
            handle.close()
    graph = p.connected_groups(closure, vectors)
    main_group_counts = Counter(graph["scenario_groups"][sid] for sid in main_ids_all)
    artifacts = {
        "features.json": p.json_bytes(vectors),
        "provenance.json": p.json_bytes(graph),
        "roots.jsonl": (selection / "selected-worlds.jsonl").read_bytes(),
    }
    hashes = {name: digest.hexdigest() for name, digest in digests.items()}
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
        hashes[name] = sha256(data).hexdigest()
    changed = any(file_hash(name) != expected for name, expected in sources.items())
    report = dict(
        scope="uniform-authored-population-not-reviewed",
        rows=len(closure),
        main_rows=main_total,
        main_class_counts=dict(labels),
        roots=len(worlds),
        components=len(graph["groups"]),
        standalone_main_components=len(main_group_counts),
        standalone_main_component_sizes=dict(Counter(main_group_counts.values())),
        source_hashes=sources,
        source_changed_during_build=changed,
        artifact_hashes=hashes,
        reviewed_rows=0,
        release_ready=False,
        required_next="Union all retained probe versions; assess final main components and test coverage; independent exact-record review",
    )
    (output / "audit.json").write_bytes(p.json_bytes(report))
    require(not changed, "Population generation sources changed")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build(args.selection, args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "rows",
                    "main_rows",
                    "standalone_main_components",
                    "standalone_main_component_sizes",
                    "release_ready",
                )
            }
        )
    )
