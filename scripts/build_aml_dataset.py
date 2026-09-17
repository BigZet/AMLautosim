"""Build an immutable v10 dataset from authored, independently reviewed sources."""

import argparse
from pathlib import Path

from scripts.aml_dataset.aml_training import build_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--casebook", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        build_dataset(args.casebook, args.protocol, args.output)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
