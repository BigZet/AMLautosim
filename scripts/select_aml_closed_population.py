"""Select uniform draft main units from a complete, byte-bound probe universe.

No model access, domain approval, or claim of final post-generation independence.
"""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from scripts.aml_dataset import aml_population_author as p
from scripts.audit_aml_history_population import file_hash, require


def select(universe, probes, output):
    universe, output = Path(universe), Path(output)
    require(not output.exists(), "Selection output already exists")
    receipt = json.loads((universe / "audit.json").read_bytes())
    require(not receipt["demo_crossings"], "Demo crosses the candidate universe")
    require(
        file_hash(universe / "provenance.json") == receipt["provenance_sha256"],
        "Universe graph checksum mismatch",
    )
    for path, expected in receipt["input_hashes"].items():
        require(file_hash(path) == expected, "Universe input changed: " + path)
    graph = json.loads((universe / "provenance.json").read_bytes())
    forbidden = {
        gid
        for gid, members in graph["groups"].items()
        if any(
            s.startswith(("demo:", "development:", "coverage-v1:", "coverage-v2:"))
            for s in members
        )
    }
    worlds, options, root_hashes = {}, defaultdict(lambda: defaultdict(list)), {}
    root_probes = {}
    for name, directory in sorted(probes.items()):
        directory = Path(directory)
        probe = json.loads((directory / "audit.json").read_bytes())
        roots_path = directory / "roots.jsonl"
        root_hashes[str(roots_path)] = file_hash(roots_path)
        require(
            root_hashes[str(roots_path)] == probe["artifact_hashes"]["roots.jsonl"],
            "Root file checksum mismatch",
        )
        require(
            str(directory / "audit.json") in receipt["input_hashes"],
            "Probe is outside the audited universe",
        )
        with roots_path.open(encoding="utf-8") as handle:
            for line in handle:
                raw = json.loads(line)
                world = p.world_from_dict(raw)
                gid = graph["scenario_groups"][name + ":" + world.id + "-opaque-0"]
                if gid in forbidden:
                    continue
                require(
                    world.id not in worlds, "Duplicate root across candidate probes"
                )
                worlds[world.id] = world
                root_probes[world.id] = name
                for role, sources in p.ROLE_SOURCES.items():
                    if world.source in sources:
                        options[gid][role].append(world.id)
    # Reserve whole connected components, never only their challenge variants.
    # Selection uses economic compatibility and sorted identities, never scores.
    reserved_new, reserved_worlds = [], []
    for role in sorted(p.ROLE_SOURCES):
        gid = next(
            (
                gid
                for gid in sorted(options)
                if gid not in reserved_new and role in options[gid]
            ),
            None,
        )
        require(gid is not None, "No independent new-combination reserve")
        reserved_new.append(gid)
        rid = min(options[gid][role])
        reserved_worlds.append(asdict(p.author_role_world(worlds[rid], role)))
    quotas = {role: 240 for role in p.ROLE_SOURCES}
    assignments = p.assign_roles(
        {gid: set(roles) for gid, roles in options.items() if gid not in reserved_new},
        quotas,
    )
    selected, manifest = [], []
    for index, (gid, role) in enumerate(sorted(assignments.items())):
        rid = min(
            options[gid][role],
            key=lambda rid: (p.ROLE_SOURCES[role].index(worlds[rid].source), rid),
        )
        world = p.author_role_world(worlds[rid], role)
        p.validate_role_world(world)
        selected.append(asdict(world))
        manifest.append(
            dict(
                root_id=rid,
                raw_component=gid,
                profile=role,
                extra_label=index % 2,
                activity_sha256=p.digest(world.activity),
                coverage_kinds=["cash", "salary_purchase"]
                if root_probes[rid] in {"deposit", "history-rails"}
                else [],
                rails=(
                    ["payment_service", "crypto_p2p", "exchange_withdrawal"]
                    if world.source == "asset"
                    else ["payment_service"]
                )
                if root_probes[rid] == "history-rails"
                else [],
                parent_ids=[graph["groups"][gid][0].split(":", 1)[1]],
            )
        )
    artifacts = {
        "selected-worlds.jsonl": p.jsonl_bytes(selected),
        "selections.json": p.json_bytes(manifest),
        "reserved-worlds.jsonl": p.jsonl_bytes(reserved_worlds),
    }
    report = dict(
        policy_version="complete-universe-uniform-25-draft-v1",
        selection_before_model_access=True,
        channel_policy="Use settlement families already authored for this root in the retained universe; retain all original bank variants and all raw bridges",
        selected_components=len(manifest),
        planned_main_rows=25 * len(manifest),
        quotas=quotas,
        reserved_new_combination_components=reserved_new,
        excluded_existing_development_demo_and_coverage_components=sorted(forbidden),
        unselected_components=sorted(
            set(options) - set(assignments) - set(reserved_new)
        ),
        source_families=dict(Counter(w["source"] for w in selected)),
        universe_receipt_sha256=file_hash(universe / "audit.json"),
        input_root_hashes=root_hashes,
        source_hashes={
            **p.compiler_hashes(),
            str(Path(__file__).relative_to(Path.cwd())): file_hash(__file__),
        },
        artifact_hashes={k: sha256(v).hexdigest() for k, v in artifacts.items()},
        reviewed_rows=0,
        release_ready=False,
        required_next="Compile uniform observations with channel coverage; repeat closure including all retained raw data; independent domain review before supervised use",
    )
    output.mkdir(parents=True)
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
    (output / "audit.json").write_bytes(p.json_bytes(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", required=True, type=Path)
    parser.add_argument("--probe", action="append", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    pairs = [value.split("=", 1) for value in args.probe]
    require(len({key for key, _ in pairs}) == len(pairs), "Duplicate probe names")
    result = select(args.universe, dict(pairs), args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "selected_components",
                    "planned_main_rows",
                    "source_families",
                    "release_ready",
                )
            }
        )
    )
