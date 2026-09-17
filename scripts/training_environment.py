"""Capture installed distributions from the interpreter doing the training."""

from importlib import metadata
import platform
import re
import sys


def collect_training_environment():
    """Return a deterministic package inventory and active-process provenance.

    This is an installed-version inventory, not a pip lockfile: it works in
    pip-free virtual environments and never resolves another Python via PATH.
    """
    packages = {}
    for distribution in metadata.distributions():
        raw_name = distribution.metadata.get("Name")
        version = distribution.version
        if not raw_name or not version:
            raise ValueError(
                "Invalid training distribution metadata: missing name or version"
            )
        name = re.sub(r"[-_.]+", "-", raw_name.lower())
        if name in packages and packages[name] != version:
            raise ValueError(f"Conflicting training distribution metadata: {name}")
        packages[name] = version
    required = ("catboost", "numpy", "pandas")
    missing = [name for name in required if not packages.get(name)]
    if missing:
        raise ValueError(
            f"Missing training distribution metadata: {', '.join(missing)}"
        )
    inventory = "".join(
        sorted(f"{name}=={version}\n" for name, version in packages.items())
    )
    return inventory, {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "executable": sys.executable,
        "prefix": sys.prefix,
        "packages": {name: packages[name] for name in required},
    }
