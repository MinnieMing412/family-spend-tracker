from __future__ import annotations

import os
import unittest

import pytest

from family_spend.adapters.google import GoogleApiSheetsClient, GoogleWorkbookFactory
from family_spend.adapters.local import FileCredentialStore, default_application_directory

WORKBOOK_ID = os.environ.get("FAMILY_SPEND_GOOGLE_INTEGRATION_WORKBOOK_ID")


@unittest.skipUnless(
    WORKBOOK_ID,
    "set FAMILY_SPEND_GOOGLE_INTEGRATION_WORKBOOK_ID to a disposable workbook",
)
@pytest.mark.integration
class LiveGoogleWorkbookIntegrationTests(unittest.TestCase):
    def test_disposable_workbook_matches_the_shared_gateway_contract(self) -> None:
        credential_store = FileCredentialStore(
            default_application_directory() / "credentials.json"
        )
        gateway = GoogleWorkbookFactory(
            GoogleApiSheetsClient(credential_store)
        ).connect(str(WORKBOOK_ID))

        gateway.validate_schema()
        configuration = gateway.load_configuration()

        self.assertIn(
            "Pets",
            tuple(category.display_name for category in configuration.categories),
        )


if __name__ == "__main__":
    unittest.main()
