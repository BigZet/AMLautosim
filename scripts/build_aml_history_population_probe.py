"""Stream a preregistered economic-history expansion; never fit or approve labels."""

import argparse
from dataclasses import asdict
from hashlib import sha256
import itertools
import json
from pathlib import Path

from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_population_rails import author_route, compile_route


PROVIDERS = ((0, 0, 0, 0, 0, 0), (0, 0, 1, 2, 3, 4), (0, 1, 2, 3, 4, 5))
ROLES = dict(
    service="artisan_owner",
    asset="collection_owner",
    refund="event_organizer",
    debt="equipment_pool_organizer",
    cost="project_coordinator",
)


def build(previous, output):
    previous, output = Path(previous), Path(output)
    if output.exists():
        raise FileExistsError(output)
    prior_raw = (previous / "roots.jsonl").read_bytes()
    prior_ids = {json.loads(line)["id"] for line in prior_raw.splitlines()}
    patterns = [
        tuple("cash" if bit else "card" for bit in bits)
        for bits in itertools.product((0, 1), repeat=6)
        if sum(bits) in (1, 3, 6)
    ]
    source_paths = [
        *p.compiler_hashes(),
        "scripts/aml_dataset/aml_population_rails.py",
        "scripts/build_aml_history_population_probe.py",
    ]
    source_hashes = {
        name: sha256(Path(name).read_bytes()).hexdigest() for name in source_paths
    }
    output.mkdir(parents=True)
    policy = dict(
        scope="prefit-history-expansion-unreviewed",
        sources=list(p.SOURCES),
        incoming=p.SOURCE_PARTITIONS,
        providers=PROVIDERS,
        patterns=patterns,
        previous_roots_sha256=sha256(prior_raw).hexdigest(),
        prior_identity_policy="Reuse existing roots, never regenerate under new identities",
        no_model_access=True,
        source_hashes=source_hashes,
    )
    (output / "prefit-policy.json").write_bytes(p.json_bytes(policy))
    rows, features, count, skipped, hashes = [], {}, 0, [], {}
    names = ("casebook.jsonl", "roots.jsonl")
    writers = {name: (output / name).open("xb") for name in names}
    digests = {name: sha256() for name in names}
    try:
        for source, incoming, providers, channels in itertools.product(
            p.SOURCES, p.SOURCE_PARTITIONS, PROVIDERS, patterns
        ):
            world = p.author_world(
                source, incoming, providers, deposit_channels=channels
            )
            if world.id in prior_ids:
                skipped.append(world.id)
                continue
            world = p.author_role_world(world, ROLES[source])
            records = (
                p.compile_probe_rows(world)
                + p.compile_variants(world, count % 2)
                + p.compile_diagnostics(world)
            )
            for kind in ("cash", "salary_purchase"):
                records.extend(
                    p.compile_coverage_case(p.author_coverage_case(world, kind))
                )
            for rail in (
                ("payment_service", "crypto_p2p", "exchange_withdrawal")
                if source == "asset"
                else ("payment_service",)
            ):
                records.extend(compile_route(author_route(world, rail)))
            vectors = p.validate_sources(records, p.protocol())
            if set(vectors) & set(features):
                raise ValueError("Repeated scenario identity")
            features.update(vectors)
            rows.extend(p.closure_row(row) for row in records)
            for name, data in (
                ("roots.jsonl", p.jsonl_bytes([asdict(world)])),
                ("casebook.jsonl", p.jsonl_bytes(records)),
            ):
                writers[name].write(data)
                digests[name].update(data)
            count += 1
            if count % 25 == 0:
                for handle in writers.values():
                    handle.flush()
                checkpoint = dict(
                    worlds=count,
                    rows=len(rows),
                    stage="financial-validation",
                    release_ready=False,
                )
                (output / "progress.json").write_bytes(p.json_bytes(checkpoint))
                print(json.dumps(checkpoint), flush=True)
    finally:
        for handle in writers.values():
            handle.close()
    hashes.update({name: value.hexdigest() for name, value in digests.items()})
    print(
        json.dumps(dict(stage="complete-closure", worlds=count, rows=len(rows))),
        flush=True,
    )
    graph = p.connected_groups(rows, features)
    for name, value in (
        ("features.json", features),
        ("provenance.json", graph),
        ("reused-roots.json", skipped),
    ):
        raw = p.json_bytes(value)
        (output / name).write_bytes(raw)
        hashes[name] = sha256(raw).hexdigest()
    changed = any(
        sha256(Path(name).read_bytes()).hexdigest() != value
        for name, value in source_hashes.items()
    )
    report = dict(
        scope="actual-history-and-rail-population-probe",
        rows=len(rows),
        roots=count,
        reused_roots=len(skipped),
        components=len(graph["groups"]),
        source_hashes=source_hashes,
        source_changed_during_build=changed,
        artifact_hashes=hashes,
        reviewed_rows=0,
        release_ready=False,
    )
    (output / "audit.json").write_bytes(p.json_bytes(report))
    if changed:
        raise ValueError("Generation sources changed during build")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build(args.previous, args.output)
    print(
        json.dumps(
            {k: result[k] for k in ("rows", "roots", "components", "release_ready")}
        ),
        flush=True,
    )
