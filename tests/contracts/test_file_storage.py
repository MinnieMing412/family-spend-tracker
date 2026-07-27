from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from family_spend.adapters.local import FileCredentialStore, FileSettingsStore
from family_spend.domain.models import LocalSettings


class FileSettingsStoreContractTests(unittest.TestCase):
    def test_settings_round_trip_without_serializing_oauth_secrets(self) -> None:
        with TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            store = FileSettingsStore(settings_path)
            settings = LocalSettings(
                workbook_id="workbook-1",
                credential_reference="credentials.json",
            )

            store.save(settings)

            self.assertEqual(settings, store.load())
            serialized = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "schema_version": 1,
                    "workbook_id": "workbook-1",
                    "credential_reference": "credentials.json",
                },
                serialized,
            )
            self.assertNotIn("token", settings_path.read_text(encoding="utf-8").lower())
            store.delete()
            self.assertIsNone(store.load())

    def test_oauth_credentials_are_private_and_separate_from_settings(self) -> None:
        with TemporaryDirectory() as directory:
            credentials_path = Path(directory) / "credentials.json"
            store = FileCredentialStore(credentials_path)
            token = "ya29." + ("synthetic" * 4)

            reference = store.save({"token": token, "refresh_token": "refresh"})

            self.assertEqual(str(credentials_path), reference)
            self.assertEqual(token, store.load(reference)["token"])
            self.assertEqual(0o600, credentials_path.stat().st_mode & 0o777)
            store.delete(reference)
            self.assertFalse(credentials_path.exists())


if __name__ == "__main__":
    unittest.main()
