import json
import tarfile

import pytest

from scripts.package_runtime import DIRECTORIES, FILES, package


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
    (source / "src/leak.txt").symlink_to(source / ".env")
    with pytest.raises(ValueError, match="Symlink"):
        package(source, tmp_path / "unsafe.tar.gz")
