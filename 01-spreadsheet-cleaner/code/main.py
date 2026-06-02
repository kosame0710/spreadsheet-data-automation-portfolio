"""
main.py — Command-line entry point for the spreadsheet cleaner.

Usage:
    python main.py                       # uses ../sample_data -> ../output
    python main.py --input DIR --output DIR

Reads every CSV in the input directory, cleans and merges them, writes a
formatted Excel workbook + CSVs + a text report to the output directory, and
prints a summary to the console.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cleaner
import report

# Make console output UTF-8 safe on any platform (Windows consoles often default
# to a legacy code page that cannot render characters like the em-dash). The
# report files are always written as UTF-8 regardless of this.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # very old Python / non-reconfigurable stream
    pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    default_in = here.parent / "sample_data"
    default_out = here.parent / "output"

    parser = argparse.ArgumentParser(description="Clean and merge messy sales CSVs.")
    parser.add_argument("--input", type=Path, default=default_in,
                        help="Directory containing input CSV files.")
    parser.add_argument("--output", type=Path, default=default_out,
                        help="Directory to write deliverables into.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    print(f"Reading CSVs from : {args.input}")
    result = cleaner.run(args.input)

    paths = report.write_outputs(result, args.output)

    print(report.build_text_report(result))
    print("\nDeliverables written:")
    for label, path in paths.items():
        print(f"  - {label:<11}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
