from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="family-spend",
        description="Import reviewed family statement transactions into Google Sheets.",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    commands.add_parser("setup", help="Create or connect a Google Sheets workbook.")

    import_parser = commands.add_parser("import", help="Import a PDF or folder.")
    import_parser.add_argument("source")
    import_parser.add_argument("--retain-cache", action="store_true")

    backfill_parser = commands.add_parser("backfill", help="Backfill a statement folder.")
    backfill_parser.add_argument("source")
    backfill_parser.add_argument("--resume", action="store_true")
    backfill_parser.add_argument("--retain-cache", action="store_true")

    commands.add_parser("status", help="Show the current connection and import status.")
    commands.add_parser("validate-workbook", help="Validate the connected workbook.")
    commands.add_parser("disconnect", help="Remove local Google credentials.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0
    print(
        f"The '{arguments.command}' command is not implemented yet.",
        file=sys.stderr,
    )
    return 2
