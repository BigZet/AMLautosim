"""Close all retained probe versions, preserving shared original identities."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from scripts.aml_dataset import aml_population_author as population


def audit(probes, development, demo, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    rows, features, partitions, hashes = [], {}, {}, {}
    consumed_vectors, shared_cached_vectors = set(), set()

    def add(row, vector, partition):
        row = population.closure_row(row)
        original = row["scenario_id"]
        sid = partition + ":" + original
        if sid in features:
            raise ValueError("Duplicate identity inside probe")
        provenance = dict(row.get("provenance", {}))
        provenance["parent_ids"] = sorted(
            set(provenance.get("parent_ids", [])) | {original}
        )
        row.update(scenario_id=sid, provenance=provenance)
        rows.append(row)
        features[sid] = vector
        consumed_vectors.add((original, population.digest(vector)))
        partitions.setdefault(partition, set()).add(sid)

    for name, directory in sorted(probes.items()):
        directory = Path(directory)
        receipt_raw = (directory / "audit.json").read_bytes()
        receipt = json.loads(receipt_raw)
        if receipt.get("source_changed_during_build"):
            raise ValueError("Source changed during probe generation")
        hashes[str(directory / "audit.json")] = sha256(receipt_raw).hexdigest()
        raw = (directory / "features.json").read_bytes()
        hashes[str(directory / "features.json")] = sha256(raw).hexdigest()
        if (
            hashes[str(directory / "features.json")]
            != receipt["artifact_hashes"]["features.json"]
        ):
            raise ValueError("Feature checksum mismatch")
        cached = json.loads(raw)
        seen, hasher = set(), sha256()
        with (directory / "casebook.jsonl").open("rb") as handle:
            for line in handle:
                hasher.update(line)
                row = json.loads(line)
                sid = row["scenario_id"]
                if sid in seen or sid not in cached:
                    raise ValueError("Probe feature roster mismatch")
                seen.add(sid)
                add(row, cached[sid], name)
        if hasher.hexdigest() != receipt["artifact_hashes"]["casebook.jsonl"]:
            raise ValueError("Probe casebook checksum or roster mismatch")
        shared_cached_vectors.update(
            (sid, population.digest(cached[sid])) for sid in set(cached) - seen
        )
        hashes[str(directory / "casebook.jsonl")] = hasher.hexdigest()
    if not shared_cached_vectors <= consumed_vectors:
        raise ValueError(
            "Shared cached features lack matching source rows in the union"
        )
    for name, path in (("development", development), ("demo", demo)):
        raw = Path(path).read_bytes()
        hashes[str(path)] = sha256(raw).hexdigest()
        extra = [json.loads(line) for line in raw.splitlines()]
        vectors = population.validate_sources(extra, population.protocol())
        for row in extra:
            add(row, vectors[row["scenario_id"]], name)
    graph = population.connected_groups(rows, features)
    population_ids = set().union(*(partitions[name] for name in probes))
    crossings = []
    groups = 0
    for gid, members in graph["groups"].items():
        members = set(members)
        groups += bool(members & population_ids)
        if members & partitions["demo"] and members - partitions["demo"]:
            crossings.append(gid)
    report = dict(
        scope="all-retained-probe-versions-with-original-identity-ancestry",
        rows=len(rows),
        components=len(graph["groups"]),
        population_components=groups,
        partitions={k: len(v) for k, v in partitions.items()},
        demo_crossings=crossings,
        input_hashes=hashes,
        release_ready=False,
        identity_policy="Namespaced snapshots link to their original scenario ID; revisions never gain independence",
    )
    output.mkdir(parents=True)
    graph_raw = population.json_bytes(graph)
    (output / "provenance.json").write_bytes(graph_raw)
    report["provenance_sha256"] = sha256(graph_raw).hexdigest()
    (output / "audit.json").write_bytes(population.json_bytes(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe", action="append", required=True, help="name=directory"
    )
    for name in ("development", "demo", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    pairs = [value.split("=", 1) for value in args.probe]
    if len({key for key, _ in pairs}) != len(pairs) or {key for key, _ in pairs} & {
        "development",
        "demo",
    }:
        parser.error("Probe names must be distinct and not reserved")
    result = audit(dict(pairs), args.development, args.demo, args.output)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "rows",
                    "components",
                    "population_components",
                    "demo_crossings",
                )
            }
        )
    )
