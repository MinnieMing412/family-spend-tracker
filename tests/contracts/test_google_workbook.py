from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from family_spend.adapters.google import GoogleWorkbookFactory
from family_spend.adapters.google_auth import (
    GOOGLE_EMAIL_SCOPE,
    GOOGLE_OPENID_SCOPE,
    GOOGLE_SHEETS_SCOPE,
    GoogleCredentialManager,
)
from family_spend.adapters.local import FileCredentialStore
from family_spend.adapters.memory import InMemorySheetsClient


class GoogleWorkbookGatewayContractTests(unittest.TestCase):
    def test_provisioning_is_retry_safe_and_loads_seeded_categories(self) -> None:
        sheets = InMemorySheetsClient()
        factory = GoogleWorkbookFactory(sheets)
        gateway = factory.create("Family Spending")

        gateway.provision_schema()
        gateway.provision_schema()
        gateway.validate_schema()
        configuration = gateway.load_configuration()

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
            sheets.worksheet_names(gateway.workbook_id),
        )
        self.assertEqual(19, len(configuration.categories))
        self.assertIn("Pets", tuple(item.display_name for item in configuration.categories))
        self.assertEqual(
            2,
            sheets.header_row_count(gateway.workbook_id, "Categories"),
        )

    def test_repeated_provisioning_preserves_user_category_edits(self) -> None:
        sheets = InMemorySheetsClient()
        gateway = GoogleWorkbookFactory(sheets).create("Family Spending")
        gateway.provision_schema()
        rows = sheets.read_rows(gateway.workbook_id, "Categories")
        pets_row = next(index for index, row in enumerate(rows) if row[1] == "Pets")
        edited = (*rows[pets_row][:3], False)
        sheets.write_rows(
            gateway.workbook_id,
            "Categories",
            pets_row + 1,
            (edited,),
        )

        gateway.provision_schema()

        reloaded = gateway.load_configuration()
        pets = next(item for item in reloaded.categories if item.display_name == "Pets")
        self.assertFalse(pets.active)

    def test_validation_rejects_renamed_columns_without_modifying_the_sheet(self) -> None:
        sheets = InMemorySheetsClient()
        gateway = GoogleWorkbookFactory(sheets).create("Family Spending")
        gateway.provision_schema()
        rows = sheets.read_rows(gateway.workbook_id, "Members")
        incompatible = (("member_id", "display_name", "aliases", "enabled"), rows[1])
        sheets.write_rows(gateway.workbook_id, "Members", 1, incompatible)
        before = sheets.read_rows(gateway.workbook_id, "Members")

        with self.assertRaisesRegex(ValueError, "Members"):
            gateway.validate_schema()

        self.assertEqual(before, sheets.read_rows(gateway.workbook_id, "Members"))

    def test_provisioning_rejects_malformed_existing_data_before_any_mutation(self) -> None:
        sheets = InMemorySheetsClient()
        gateway = GoogleWorkbookFactory(sheets).create("Malformed")
        sheets.rename_worksheet(gateway.workbook_id, "Sheet1", "Members")
        sheets.write_rows(
            gateway.workbook_id,
            "Members",
            1,
            (("member_id", "wrong"), ("Member ID", "Wrong")),
        )
        names_before = sheets.worksheet_names(gateway.workbook_id)
        rows_before = sheets.read_rows(gateway.workbook_id, "Members")

        with self.assertRaisesRegex(ValueError, "Members"):
            gateway.provision_schema()

        self.assertEqual(names_before, sheets.worksheet_names(gateway.workbook_id))
        self.assertEqual(rows_before, sheets.read_rows(gateway.workbook_id, "Members"))
        self.assertIsNone(sheets.schema_version(gateway.workbook_id))

    def test_validation_rejects_type_incompatible_configuration_values(self) -> None:
        sheets = InMemorySheetsClient()
        gateway = GoogleWorkbookFactory(sheets).create("Family Spending")
        gateway.provision_schema()
        sheets.write_rows(
            gateway.workbook_id,
            "Categories",
            3,
            (("groceries", "Groceries", "first", True),),
        )

        with self.assertRaisesRegex(ValueError, "sort_order"):
            gateway.validate_schema()

    def test_configuration_rows_are_loaded_into_domain_records(self) -> None:
        sheets = InMemorySheetsClient()
        gateway = GoogleWorkbookFactory(sheets).create("Family Spending")
        gateway.provision_schema()
        sheets.write_rows(
            gateway.workbook_id,
            "Members",
            3,
            (("member-1", "Member One", "ONE|M ONE", True),),
        )
        sheets.write_rows(
            gateway.workbook_id,
            "Accounts",
            3,
            (("amex-1", "amex", "ending-12345", "member-1", "AMEX", True),),
        )
        sheets.write_rows(
            gateway.workbook_id,
            "Merchant Rules",
            3,
            (
                (
                    "rule-1",
                    "exact",
                    "EXAMPLE",
                    "EXAMPLE",
                    "dining",
                    1,
                    True,
                    "2026-07-27T00:00:00+00:00",
                ),
            ),
        )

        configuration = gateway.load_configuration()

        self.assertEqual("Member One", configuration.members[0].display_name)
        self.assertEqual(("ONE", "M ONE"), configuration.members[0].aliases)
        self.assertEqual("amex-1", configuration.accounts[0].account_id)
        self.assertEqual("rule-1", configuration.merchant_rules[0].rule_id)


class GoogleCredentialManagerContractTests(unittest.TestCase):
    def test_authorization_uses_browser_flow_with_only_the_sheets_scope(self) -> None:
        with TemporaryDirectory() as directory:
            store = FileCredentialStore(Path(directory) / "credentials.json")
            observed: dict[str, Any] = {}

            class Credentials:
                def to_json(self) -> str:
                    return '{"token": "synthetic", "refresh_token": "refresh"}'

            class Flow:
                def run_local_server(self, *, port: int, open_browser: bool) -> Credentials:
                    observed["port"] = port
                    observed["open_browser"] = open_browser
                    return Credentials()

            def build_flow(client_secrets: Path, scopes: tuple[str, ...]) -> Flow:
                observed["client_secrets"] = client_secrets
                observed["scopes"] = scopes
                return Flow()

            identity = "person" + "@" + "example.invalid"
            manager = GoogleCredentialManager(
                store,
                flow_builder=build_flow,
                identity_resolver=lambda credentials: identity,
            )

            reference = manager.authorize(Path("client-secrets.json"))

            self.assertEqual(
                (GOOGLE_OPENID_SCOPE, GOOGLE_EMAIL_SCOPE, GOOGLE_SHEETS_SCOPE),
                observed["scopes"],
            )
            self.assertTrue(observed["open_browser"])
            self.assertEqual(0, observed["port"])
            self.assertEqual("synthetic", store.load(reference)["token"])
            self.assertEqual(identity, manager.identity(reference))

    def test_failed_setup_can_restore_previous_credentials(self) -> None:
        with TemporaryDirectory() as directory:
            store = FileCredentialStore(Path(directory) / "credentials.json")
            previous = {
                "token": "previous",
                "refresh_token": "previous-refresh",
                "_family_spend_identity": "previous-account",
            }
            store.save(previous)

            class Credentials:
                def to_json(self) -> str:
                    return '{"token": "replacement", "refresh_token": "replacement-refresh"}'

            class Flow:
                def run_local_server(self, *, port: int, open_browser: bool) -> Credentials:
                    del port, open_browser
                    return Credentials()

            manager = GoogleCredentialManager(
                store,
                flow_builder=lambda client_secrets, scopes: Flow(),
                identity_resolver=lambda credentials: "replacement-account",
            )

            manager.authorize(Path("replacement.json"))
            manager.rollback_authorization()

            self.assertEqual(previous, store.load(store.reference))


if __name__ == "__main__":
    unittest.main()
