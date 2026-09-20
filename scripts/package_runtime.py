"""Build a deterministic, allowlisted deployment source archive from the worktree."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile

FILES = (
    ".dockerignore",
    ".env.example",
    "docker-compose.yml",
    "deploy/compose.image.yml",
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
    "resources/catboost_models/aml-game-v1",
    "resources/catboost_models/aml-game-relaxed-v1",
    "resources/catboost_models/aml-game-attributes-v1",
    "resources/catboost_models/aml-game-attribute-context-v1",
    "resources/catboost_models/aml-game-attribute-context-unlimited-v1",
    "resources/catboost_models/aml-game-organizer-settings-v1",
)


def verify_archive(path: Path):
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or any(not m.isfile() for m in members):
            raise ValueError("Invalid archive entries")
        manifest = json.load(archive.extractfile("RELEASE-CHECKSUMS.json"))
        if set(names) != set(manifest) | {"RELEASE-CHECKSUMS.json"}:
            raise ValueError("Manifest file list mismatch")
        if not set(FILES).issubset(manifest):
            raise ValueError("Required runtime files missing")
        for directory in DIRECTORIES:
            if not any(name.startswith(directory + "/") for name in manifest):
                raise ValueError(f"Missing runtime directory: {directory}")
        for name, checksum in manifest.items():
            if name not in FILES and not any(name.startswith(d + "/") for d in DIRECTORIES):
                raise ValueError(f"Unexpected runtime file: {name}")
            parts = Path(name).parts
            if name not in FILES and (
                any(part.startswith(".") for part in parts)
                or Path(name).name in {"credentials.json", "cookies.json"}
                or Path(name).suffix in {".dump", ".db", ".sqlite", ".sqlite3", ".bak"}
            ):
                raise ValueError(f"Private runtime file: {name}")
            if hashlib.sha256(archive.extractfile(name).read()).hexdigest() != checksum:
                raise ValueError(f"Checksum mismatch: {name}")
    return manifest


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
    if destination.exists():
        raise FileExistsError(destination)
    fd, temporary = tempfile.mkstemp(prefix=".runtime-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    for name, data in sorted(contents.items()):
                        info = tarfile.TarInfo(name)
                        info.size, info.mode, info.mtime = len(data), 0o644, 0
                        archive.addfile(info, io.BytesIO(data))
            output.flush()
            os.fsync(output.fileno())
        verify_archive(Path(temporary))
        # Atomic, exclusive publication on the same filesystem (no overwrite).
        os.link(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
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
