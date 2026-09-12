"""Validate game configuration without a server or database.

API lifespan and seed call the same validate_configuration_files function.
NiceGUI consumes validated contracts over HTTP, never the config files.

    python -m scripts.validate_config
    python -m scripts.validate_config --config-dir /path/to/other/config

Exit status is 0 for valid configuration and 1 on validation failure.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import game configuration only when validation runs, after --config-dir is set.
# Importing earlier would cache the default directory and silently ignore the flag.
def validate_configuration_files() -> None:
    from src.aml_workshop_simulator.schemas.catalog_config import (
        validate_configuration_files as validate,
    )

    validate()


Validator = Callable[[], None]
VALIDATORS: list[tuple[str, Validator]] = [
    ("schemas.catalog_config.validate_configuration_files", validate_configuration_files),
]


def run_validators(validators: list[tuple[str, Validator]] = VALIDATORS) -> list[str]:
    """Run every validator and collect failures instead of stopping at the
    first one, so a single broken file doesn't hide unrelated problems.
    """
    errors: list[str] = []
    for label, validator in validators:
        try:
            validator()
        except Exception as exc:  # noqa: BLE001 - report every failure, hide none
            errors.append(f"[{label}] {exc}")
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-dir",
        help="Override AML_GAME_CONFIG_DIR for this run only (defaults to config/).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.config_dir:
        os.environ["AML_GAME_CONFIG_DIR"] = args.config_dir

    errors = run_validators()
    if errors:
        for line in errors:
            print(line, file=sys.stderr)
        print(f"Конфигурация невалидна: {len(errors)} ошибка(и).", file=sys.stderr)
        return 1

    print("Конфигурация валидна.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
