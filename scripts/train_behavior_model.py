"""Train a new behavior-covered CatBoost experiment."""

import argparse
from scripts.behavior_model import train

if __name__ == "__main__":
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    train(args.dataset, args.output)
