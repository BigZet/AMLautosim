"""Validate a staged compatibility package before publishing its release."""

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


@contextmanager
def staged_package(output, *, refresh=False):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    existed = output.exists()
    if existed and not refresh:
        raise FileExistsError(output)
    with tempfile.TemporaryDirectory(
        prefix=".package-check-", dir=output.parent
    ) as temp:
        staged = Path(temp) / "package"
        if existed:
            shutil.copytree(output, staged)
        yield staged
        if existed:
            # Refresh changes only release metadata; verify that invariant before publication.
            before = {
                str(p.relative_to(output)): p.read_bytes()
                for p in output.rglob("*")
                if p.is_file() and p.name != "release.json"
            }
            after = {
                str(p.relative_to(staged)): p.read_bytes()
                for p in staged.rglob("*")
                if p.is_file() and p.name != "release.json"
            }
            require(before == after, "Refresh must not change model artifacts")
            os.replace(staged / "release.json", output / "release.json")
        else:
            staged.rename(output)
