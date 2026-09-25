"""Server-owned package locations; model pins are never filesystem paths."""

import json
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "resources/catboost_models"
REGISTRY_PATH = PACKAGE_ROOT / "registry.json"


def registry() -> dict:
    value = json.loads(REGISTRY_PATH.read_bytes())
    if value["version"] != 1:
        raise ValueError("Unsupported model registry")
    names = set()
    for entry in value["packages"]:
        name = entry["path"]
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or "/" in name
            or "\\" in name
            or name in (".", "..")
        ):
            raise ValueError("Invalid registered package path")
        if name in names or entry["support"] not in ("current", "legacy", "research"):
            raise ValueError("Invalid registered package entry")
        names.add(name)
        if not (PACKAGE_ROOT / name).resolve().is_relative_to(PACKAGE_ROOT.resolve()):
            raise ValueError("Registered package path escapes root")
    if value["current_runtime"] not in names:
        raise ValueError("Missing current runtime package")
    return value


def classifier_paths() -> tuple[Path, ...]:
    return tuple(
        PACKAGE_ROOT / entry["path"]
        for entry in registry()["packages"]
        if entry["support"] in ("current", "legacy")
        and entry["kind"] == "game-classifier"
    )
