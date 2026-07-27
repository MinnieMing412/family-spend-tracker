from __future__ import annotations

import unittest
from io import StringIO
from pathlib import Path

from family_spend.adapters.memory import (
    InMemoryCredentialManager,
    InMemorySettingsStore,
    InMemoryWorkbookFactory,
)
from family_spend.application import FamilySpendApplication
from family_spend.cli import main
from family_spend.domain.models import LocalSettings


class SetupCliAcceptanceTests(unittest.TestCase):
    def test_setup_creates_a_compatible_workbook_and_saves_connection(self) -> None:
        settings = InMemorySettingsStore()
        credentials = InMemoryCredentialManager()
        workbooks = InMemoryWorkbookFactory()
        application = FamilySpendApplication(
            settings=settings,
            credentials=credentials,
            workbooks=workbooks,
        )
        stdout = StringIO()
        stderr = StringIO()

        exit_code = main(
            [
                "setup",
                "--client-secrets",
                "client-secrets.json",
                "--workbook-name",
                "Family Spending",
            ],
            application=application,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertEqual("", stderr.getvalue())
        saved = settings.load()
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertTrue(credentials.contains(saved.credential_reference))
        workbook = workbooks.connect(saved.workbook_id)
        workbook.validate_schema()
        self.assertEqual(
            (
                "Transactions",
                "Members",
                "Accounts",
                "Categories",
                "Merchant Rules",
                "Imports",
                "Dashboard",
            ),
            workbook.worksheet_names(),
        )
        self.assertIn("Pets", stdout.getvalue())
        self.assertIn("Uncategorized", stdout.getvalue())

    def test_setup_connects_an_existing_compatible_workbook_by_url(self) -> None:
        settings = InMemorySettingsStore()
        credentials = InMemoryCredentialManager()
        workbooks = InMemoryWorkbookFactory()
        existing = workbooks.create("Existing")
        existing.provision_schema()
        application = FamilySpendApplication(
            settings=settings,
            credentials=credentials,
            workbooks=workbooks,
        )
        stdout = StringIO()
        stderr = StringIO()

        exit_code = main(
            [
                "setup",
                "--client-secrets",
                "client-secrets.json",
                "--workbook-url",
                f"https://docs.google.com/spreadsheets/d/{existing.workbook_id}/edit",
            ],
            application=application,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(0, exit_code, stderr.getvalue())
        saved = settings.load()
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(existing.workbook_id, saved.workbook_id)
        self.assertIn(existing.workbook_id, stdout.getvalue())

    def test_validate_workbook_reports_a_compatible_connection(self) -> None:
        settings = InMemorySettingsStore()
        credentials = InMemoryCredentialManager()
        workbooks = InMemoryWorkbookFactory()
        workbook = workbooks.create("Existing")
        workbook.provision_schema()
        reference = credentials.authorize(Path("client-secrets.json"))
        settings.save(LocalSettings(workbook.workbook_id, reference))
        application = FamilySpendApplication(
            settings=settings,
            credentials=credentials,
            workbooks=workbooks,
        )
        stdout = StringIO()
        stderr = StringIO()

        exit_code = main(
            ["validate-workbook"],
            application=application,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertEqual("", stderr.getvalue())
        self.assertIn("compatible", stdout.getvalue())

    def test_status_reports_connection_identity_imports_exceptions_and_cache(self) -> None:
        settings = InMemorySettingsStore()
        credentials = InMemoryCredentialManager()
        workbooks = InMemoryWorkbookFactory()
        workbook = workbooks.create("Existing")
        workbook.provision_schema()
        reference = credentials.authorize(Path("client-secrets.json"))
        credentials.commit_authorization()
        settings.save(LocalSettings(workbook.workbook_id, reference))
        application = FamilySpendApplication(
            settings=settings,
            credentials=credentials,
            workbooks=workbooks,
            cache_location=Path("/private/cache/family-spend"),
        )
        stdout = StringIO()

        exit_code = main(
            ["status"],
            application=application,
            stdout=stdout,
            stderr=StringIO(),
        )

        self.assertEqual(0, exit_code)
        output = stdout.getvalue()
        self.assertIn("Authenticated Google identity: Test Google account", output)
        self.assertIn("Last successful import: none", output)
        self.assertIn("Unresolved exceptions: none recorded", output)
        self.assertIn("Retained cache location: /private/cache/family-spend", output)

    def test_disconnect_removes_local_access_but_keeps_the_workbook(self) -> None:
        settings = InMemorySettingsStore()
        credentials = InMemoryCredentialManager()
        workbooks = InMemoryWorkbookFactory()
        workbook = workbooks.create("Existing")
        workbook.provision_schema()
        reference = credentials.authorize(Path("client-secrets.json"))
        settings.save(LocalSettings(workbook.workbook_id, reference))
        application = FamilySpendApplication(
            settings=settings,
            credentials=credentials,
            workbooks=workbooks,
        )
        stdout = StringIO()
        stderr = StringIO()

        exit_code = main(
            ["disconnect"],
            application=application,
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertIsNone(settings.load())
        self.assertFalse(credentials.contains(reference))
        workbooks.connect(workbook.workbook_id).validate_schema()
        self.assertIn("Local Google access removed", stdout.getvalue())

    def test_failed_setup_preserves_the_previous_local_connection(self) -> None:
        settings = InMemorySettingsStore()
        credentials = InMemoryCredentialManager()
        workbooks = InMemoryWorkbookFactory()
        previous = workbooks.create("Previous")
        previous.provision_schema()
        previous_reference = credentials.authorize(Path("previous-client.json"))
        credentials.commit_authorization()
        previous_settings = LocalSettings(previous.workbook_id, previous_reference)
        settings.save(previous_settings)
        application = FamilySpendApplication(
            settings=settings,
            credentials=credentials,
            workbooks=workbooks,
        )
        stderr = StringIO()

        exit_code = main(
            [
                "setup",
                "--client-secrets",
                "replacement-client.json",
                "--workbook-url",
                "https://docs.google.com/spreadsheets/d/missing/edit",
            ],
            application=application,
            stdout=StringIO(),
            stderr=stderr,
        )

        self.assertEqual(1, exit_code)
        self.assertEqual(previous_settings, settings.load())
        self.assertTrue(credentials.contains(previous_reference))
        self.assertFalse(credentials.contains("memory:replacement-client.json"))

    def test_setup_rejects_a_non_google_workbook_url(self) -> None:
        application = FamilySpendApplication(
            settings=InMemorySettingsStore(),
            credentials=InMemoryCredentialManager(),
            workbooks=InMemoryWorkbookFactory(),
        )
        stderr = StringIO()

        exit_code = main(
            [
                "setup",
                "--client-secrets",
                "client-secrets.json",
                "--workbook-url",
                "https://example.invalid/spreadsheets/d/workbook-1/edit",
            ],
            application=application,
            stdout=StringIO(),
            stderr=stderr,
        )

        self.assertEqual(1, exit_code)
        self.assertIn("docs.google.com", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
