"""Check recorded human review without inventing approvals or generating labels."""

import argparse
from pathlib import Path
from scripts.aml_dataset.joint_review import check_joint_review


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--require-blind", action="store_true")
    args = parser.parse_args()
    try:
        print(check_joint_review(args.directory, args.require_blind))
    except (ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
