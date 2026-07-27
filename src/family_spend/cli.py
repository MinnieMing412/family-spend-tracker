from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Never, TextIO

from family_spend.application import CliApplication
from family_spend.errors import FamilySpendError


class RedactingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise FamilySpendError(message, exit_code=2)


def build_parser() -> argparse.ArgumentParser:
    parser = RedactingArgumentParser(
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


def main(
    argv: Sequence[str] | None = None,
    *,
    application: CliApplication | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    try:
        parser = build_parser()
        arguments = parser.parse_args(argv)
        if arguments.command is None:
            parser.print_help(file=stdout)
            return 0
        if arguments.command == "status" and application is not None:
            print(application.status(), file=stdout)
            return 0
        print(
            f"The '{arguments.command}' command is not implemented yet.",
            file=stderr,
        )
        return 2
    except FamilySpendError as error:
        print(error.user_message(), file=stderr)
        return error.exit_code
    except Exception as error:
        translated_error = FamilySpendError(str(error))
        print(translated_error.user_message(), file=stderr)
        return translated_error.exit_code
