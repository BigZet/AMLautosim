"""Build a deterministic, allowlisted deployment source archive from the worktree."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

FILES = (
    ".dockerignore",
    ".env.example",
    "docker-compose.yml",
    "requirements.txt",
    "requirements.in",
    "alembic.ini",
    "deploy/Dockerfile",
    "docs/deployment.md",
    "docs/operations.md",
)
DIRECTORIES = (
    "src",
    "scripts",
    "migrations",
    "config",
    "resources/catboost_models/integration-v2-final",
)


def package(root: Path, destination: Path):
    root = root.resolve()
    paths = [root / name for name in FILES]
    for name in DIRECTORIES:
        folder = root / name
        if not folder.is_dir():
            raise ValueError(f"Missing runtime directory: {name}")
        paths.extend(p for p in folder.rglob("*") if p.is_file() or p.is_symlink())
    contents = {}
    for path in sorted(set(paths)):
        relative = path.relative_to(root)
        if (
            "__pycache__" in relative.parts
            or path.suffix in (".pyc", ".pyo")
            or path.name == ".DS_Store"
        ):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Symlink outside the release contract: {relative}")
        if (
            any(part.startswith(".") for part in relative.parts)
            and relative.as_posix() not in FILES
        ):
            raise ValueError(f"Unexpected hidden file in runtime sources: {relative}")
        contents[relative.as_posix()] = path.read_bytes()
    manifest = {
        name: hashlib.sha256(data).hexdigest() for name, data in contents.items()
    }
    contents["RELEASE-CHECKSUMS.json"] = (
        json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental replacement of an approved release.
    with destination.open("xb") as output:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=output, mtime=0
        ) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for name, data in sorted(contents.items()):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.mtime = len(data), 0o644, 0
                    archive.addfile(info, io.BytesIO(data))
    return {
        "files": len(manifest),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(package(Path(__file__).resolve().parents[1], args.output), indent=2)
    )


if __name__ == "__main__":
    main()
