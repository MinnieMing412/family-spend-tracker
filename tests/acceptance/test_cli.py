from __future__ import annotations

import os
import subprocess
import sys
import unittest
from io import StringIO
from pathlib import Path

from family_spend.adapters.memory import InMemorySettingsStore, InMemoryWorkbookGateway
from family_spend.application import FamilySpendApplication
from family_spend.cli import main
from family_spend.domain.models import LocalSettings, WorkbookConfig
from family_spend.errors import FamilySpendError

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

    def test_import_of_a_missing_source_fails_without_claiming_success(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")

        result = subprocess.run(
            [sys.executable, "-m", "family_spend", "import", "sample.pdf"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("does not exist", result.stderr)
        self.assertNotIn("Parse complete", result.stdout)

    def test_status_reads_injected_boundary_state(self) -> None:
        settings = InMemorySettingsStore()
        settings.save(
            LocalSettings(
                workbook_id="workbook-1",
                credential_reference="keyring:family-spend",
            )
        )
        workbook = InMemoryWorkbookGateway(WorkbookConfig((), (), (), ()))
        application = FamilySpendApplication(settings=settings, workbook=workbook)
        stdout = StringIO()
        stderr = StringIO()

        exit_code = main(
            ["status"],
            application=application,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr.getvalue())
        self.assertIn("workbook-1", stdout.getvalue())

    def test_boundary_failure_is_redacted_by_the_cli(self) -> None:
        token = "gho_" + ("x" * 32)
        email = "person" + "@" + "example.invalid"
        account = "-".join(("1234", "5678", "9012", "3456"))

        class FailingSettingsStore(InMemorySettingsStore):
            def load(self) -> LocalSettings | None:
                raise FamilySpendError(
                    f"Token {token} failed for {email} on account {account}",
                    exit_code=7,
                )

        application = FamilySpendApplication(
            settings=FailingSettingsStore(),
            workbook=InMemoryWorkbookGateway(WorkbookConfig((), (), (), ())),
        )
        stdout = StringIO()
        stderr = StringIO()

        exit_code = main(
            ["status"],
            application=application,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(7, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertNotIn(token, stderr.getvalue())
        self.assertNotIn(email, stderr.getvalue())
        self.assertNotIn(account, stderr.getvalue())
        self.assertIn("[REDACTED_TOKEN]", stderr.getvalue())
        self.assertIn("[REDACTED_EMAIL]", stderr.getvalue())
        self.assertIn("ending-3456", stderr.getvalue())

    def test_argument_parser_failure_is_redacted_by_the_cli(self) -> None:
        token = "gho_" + ("y" * 32)
        stdout = StringIO()
        stderr = StringIO()

        exit_code = main([token], stdout=stdout, stderr=stderr)

        self.assertEqual(2, exit_code)
        self.assertNotIn(token, stderr.getvalue())
        self.assertIn("[REDACTED_TOKEN]", stderr.getvalue())

    def test_unexpected_boundary_failure_is_redacted_by_the_cli(self) -> None:
        account = " ".join(("1234", "5678"))

        class FailingSettingsStore(InMemorySettingsStore):
            def load(self) -> LocalSettings | None:
                raise ValueError(f"Invalid account {account}")

        application = FamilySpendApplication(
            settings=FailingSettingsStore(),
            workbook=InMemoryWorkbookGateway(WorkbookConfig((), (), (), ())),
        )
        stdout = StringIO()
        stderr = StringIO()

        exit_code = main(
            ["status"],
            application=application,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertNotIn(account, stderr.getvalue())
        self.assertIn("ending-5678", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
