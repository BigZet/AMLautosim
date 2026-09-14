"""Generate review material; pilot/release require recorded joint reviews."""

import argparse
from pathlib import Path
from scripts.aml_dataset.expanded import build, write_package


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260914)
    parser.add_argument("--reference-dir", type=Path)
    parser.add_argument("--pilot-dir", type=Path)
    parser.add_argument(
        "--stage", choices=["review", "pilot", "release"], default="review"
    )
    args = parser.parse_args()
    if args.stage != "review":
        if args.reference_dir is None:
            parser.error(
                "Joint rubric review is pending; --reference-dir with recorded review is required"
            )
        from scripts.aml_dataset.mass_release import generate_mass

        try:
            print(
                generate_mass(
                    args.reference_dir,
                    args.output,
                    args.stage,
                    args.seed,
                    args.pilot_dir,
                )
            )
        except (ValueError, KeyError) as error:
            parser.error(str(error))
        return
    print(write_package(build(args.seed), args.output))


if __name__ == "__main__":
    main()
