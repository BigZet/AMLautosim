"""Train the frozen AML experiment; never select using test predictions."""

import argparse
from scripts.catboost_pipeline import train


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=20260914)
    args = parser.parse_args()
    train(args.dataset, args.output, args.seed)


if __name__ == "__main__":
    main()
