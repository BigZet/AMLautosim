"""Evaluate a saved model without fitting; write a new immutable report directory."""

import argparse
from scripts.catboost_pipeline import evaluate


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pairs", default="resources/aml_dataset/review-v2-final-1")
    args = parser.parse_args()
    evaluate(args.dataset, args.model, args.output, args.pairs)


if __name__ == "__main__":
    main()
