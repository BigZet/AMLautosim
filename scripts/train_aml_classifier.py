"""Train the frozen AML classifier protocol using train/validation only."""

import argparse
from pathlib import Path

from scripts.aml_classifier import train


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frozen-demo", required=True, type=Path)
    args = parser.parse_args()
    train(args.dataset, args.protocol, args.output, frozen_demo=args.frozen_demo)


if __name__ == "__main__":
    main()
