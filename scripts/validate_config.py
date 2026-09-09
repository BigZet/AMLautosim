"""Standalone, DB-free config validation.

Every process that reads config/*.json (the API, both Streamlit UIs) fails
fast on its own if the config is broken — but that only catches a bad
config once that specific process happens to start. This script runs the
same checks up front, with no server and no database, so it can gate a
deploy before any process starts:

    python -m scripts.validate_config
    python -m scripts.validate_config --config-dir /path/to/other/config

Exit code 0 = config is sound, 1 = at least one check failed. Meant to run
as a `docker-compose` precondition or a CI step, not to be imported by the
services themselves — they call `validate_configuration_files()` directly
(see `api/main.py`'s lifespan, and the equivalent startup hook the two
Streamlit apps should call before rendering anything).
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

from src_new.aml_workshop_simulator.schemas.catalog_config import (  # noqa: E402
    validate_configuration_files,
)

# Every check here must be static: no DB session, no running app. A check
# that needs live data (e.g. reconciling config against `action_cards` rows
# in the DB, like admin.common.validate_game_config does) belongs in a
# migration/seed step instead, not here.
#
# label -> zero-arg callable that raises on failure.
Validator = Callable[[], None]
VALIDATORS: list[tuple[str, Validator]] = [
    ("schemas.catalog_config.validate_configuration_files", validate_configuration_files),
    # ("domain.rules.validate_structure(base_round)", ...),  # add as written
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
