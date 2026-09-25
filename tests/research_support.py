"""Generate test inputs from source without keeping historical dataset artifacts."""

from functools import cache
import json
from pathlib import Path
from tempfile import TemporaryDirectory

_workspace = TemporaryDirectory(prefix="aml-research-fixtures-")


@cache
def pilot_path() -> Path:
    from scripts.aml_dataset.aml_casebook import build_casebook

    path = Path(_workspace.name) / "casebook.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in build_casebook()),
        encoding="utf-8",
    )
    return path
