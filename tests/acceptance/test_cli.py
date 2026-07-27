from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CliAcceptanceTests(unittest.TestCase):
    def test_help_lists_the_product_commands(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")

        result = subprocess.run(
            [sys.executable, "-m", "family_spend", "--help"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        for command in (
            "setup",
            "import",
            "backfill",
            "status",
            "validate-workbook",
            "disconnect",
        ):
            self.assertIn(command, result.stdout)

    def test_unimplemented_command_fails_without_claiming_success(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")

        result = subprocess.run(
            [sys.executable, "-m", "family_spend", "status"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("not implemented yet", result.stderr)


if __name__ == "__main__":
    unittest.main()
