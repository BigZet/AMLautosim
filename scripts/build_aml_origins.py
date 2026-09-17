"""Generate only bounded unreviewed economic-origin candidates."""

import argparse
import json

from scripts.aml_dataset.aml_origins import build_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(build_origins(args.output), indent=2))


if __name__ == "__main__":
    main()
