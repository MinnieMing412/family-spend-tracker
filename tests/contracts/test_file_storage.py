from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from family_spend.adapters.local import (
    FileCheckpointStore,
    FileCredentialStore,
    FileSettingsStore,
)
from family_spend.domain.models import BackfillCheckpoint, LocalSettings


class FileSettingsStoreContractTests(unittest.TestCase):
    def test_failed_private_write_removes_its_temporary_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings_path = root / "settings.json"
            store = FileSettingsStore(settings_path)

            with (
                patch.object(Path, "replace", side_effect=OSError("disk unavailable")),
                self.assertRaisesRegex(OSError, "disk unavailable"),
            ):
                store.save(LocalSettings("workbook-1", "credentials.json"))

            self.assertFalse(settings_path.exists())
            self.assertEqual((), tuple(root.glob(".settings.json.*")))

    def test_backfill_checkpoint_round_trip_is_private(self) -> None:
        with TemporaryDirectory() as directory:
            store = FileCheckpointStore(Path(directory) / "checkpoints")
            root_id = "a" * 64
            checkpoint = BackfillCheckpoint(root_id, "plan-1", ("hash-1",), ("bad.pdf",))

            store.save(checkpoint)

            path = store.path_for(root_id)
            self.assertEqual(checkpoint, store.load(root_id))
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)
            store.delete(root_id)
            self.assertIsNone(store.load(root_id))

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
