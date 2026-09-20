import json
import tarfile

import pytest

from scripts.package_runtime import DIRECTORIES, FILES, package
from scripts import package_runtime


def test_release_is_reproducible_and_excludes_local_data(tmp_path):
    source = tmp_path / "source"
    for name in FILES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    for name in DIRECTORIES:
        path = source / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "file.txt").write_text(name)
    (source / ".env").write_text("secret")
    private = source / "resources/aml_dataset/private.csv"
    private.parent.mkdir(parents=True)
    private.write_text("private")
    first, second = tmp_path / "first.tar.gz", tmp_path / "second.tar.gz"
    assert package(source, first) == package(source, second)
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        names = archive.getnames()
        assert ".env" not in names and "resources/aml_dataset/private.csv" not in names
        assert (
            len(json.load(archive.extractfile("RELEASE-CHECKSUMS.json")))
            == len(names) - 1
        )
    with pytest.raises(FileExistsError):
        package(source, first)


def test_release_rejects_symlinks(tmp_path):
    source = tmp_path / "source"
    for name in FILES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    for name in DIRECTORIES:
        (source / name).mkdir(parents=True, exist_ok=True)
    (source / ".env").write_text("secret")
    try:
        (source / "src/leak.txt").symlink_to(source / ".env")
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows requires Developer Mode or symlink privileges")
        raise
    with pytest.raises(ValueError, match="Symlink"):
        package(source, tmp_path / "unsafe.tar.gz")


def test_failed_verification_does_not_publish(tmp_path, monkeypatch):
    source = tmp_path / "source"
    for name in FILES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    for name in DIRECTORIES:
        folder = source / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "file.txt").write_text(name)
    def fail(_):
        raise ValueError("bad checksum")
    monkeypatch.setattr(package_runtime, "verify_archive", fail)
    destination = tmp_path / "release.tar.gz"
    with pytest.raises(ValueError, match="bad checksum"):
        package(source, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".runtime-*"))


def test_archive_verifier_rejects_corruption_and_private_files(tmp_path):
    import io

    source = tmp_path / "source"
    for name in FILES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    for name in DIRECTORIES:
        folder = source / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "file.txt").write_text(name)
    good = tmp_path / "good.tar.gz"
    package(source, good)
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(good) as original, tarfile.open(bad, "w:gz") as modified:
        for member in original.getmembers():
            data = original.extractfile(member).read()
            if member.name == "requirements.txt":
                data += b"tampered"
            member.size = len(data)
            modified.addfile(member, io.BytesIO(data))
    with pytest.raises(ValueError, match="Checksum mismatch"):
        package_runtime.verify_archive(bad)
    (source / "config/credentials.json").write_text("private")
    with pytest.raises(ValueError, match="Private runtime file"):
        package(source, tmp_path / "private.tar.gz")
    assert not (tmp_path / "private.tar.gz").exists()
