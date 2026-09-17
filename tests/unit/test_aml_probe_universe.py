from copy import deepcopy
from hashlib import sha256
import json

import pytest

from scripts.audit_aml_probe_universe import audit
from scripts.aml_dataset import aml_population_author as population


def save_probe(path, rows, vectors):
    path.mkdir()
    artifacts = {
        "casebook.jsonl": population.jsonl_bytes(rows),
        "features.json": population.json_bytes(vectors),
    }
    for name, data in artifacts.items():
        (path / name).write_bytes(data)
    (path / "audit.json").write_bytes(
        population.json_bytes(
            {
                "artifact_hashes": {
                    k: sha256(v).hexdigest() for k, v in artifacts.items()
                }
            }
        )
    )


@pytest.mark.parametrize(
    "defect", [None, "missing_shared_row", "changed_shared_vector"]
)
def test_versioned_observations_keep_original_ancestry_and_shared_cache_is_bound(
    tmp_path, defect
):
    def rows(source):
        return population.compile_probe_rows(
            population.author_world(source, (1, 1, 1), (0, 0, 1, 2, 3, 4))
        )

    raw = rows("service")
    vectors = population.validate_sources(raw, population.protocol())
    altered = deepcopy(raw)
    altered[0]["public_snapshot"]["config"]["behavior"]["profile"]["description"] += (
        " Revision of narrative."
    )
    shared = deepcopy(vectors)
    if defect == "missing_shared_row":
        shared["nonexistent-source"] = deepcopy(next(iter(vectors.values())))
    elif defect == "changed_shared_vector":
        shared[raw[1]["scenario_id"]]["observed_inactivity"] = 999
    save_probe(tmp_path / "raw", raw, vectors)
    save_probe(tmp_path / "revision", altered[:1], shared)
    dev, demo = tmp_path / "dev.jsonl", tmp_path / "demo.jsonl"
    dev.write_bytes(population.jsonl_bytes(rows("refund")))
    demo.write_bytes(population.jsonl_bytes(rows("debt")))
    if defect:
        with pytest.raises(ValueError, match="Shared cached"):
            audit(
                {"raw": tmp_path / "raw", "revision": tmp_path / "revision"},
                dev,
                demo,
                tmp_path / "result",
            )
        assert not (tmp_path / "result").exists()
    else:
        result = audit(
            {"raw": tmp_path / "raw", "revision": tmp_path / "revision"},
            dev,
            demo,
            tmp_path / "result",
        )
        graph = json.loads((tmp_path / "result/provenance.json").read_bytes())
        sid = raw[0]["scenario_id"]
        assert (
            graph["scenario_groups"]["raw:" + sid]
            == graph["scenario_groups"]["revision:" + sid]
        )
        assert not result["demo_crossings"]
