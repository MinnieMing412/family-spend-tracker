"""Local filesystem adapters for non-workbook application state."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from family_spend.domain.models import LocalSettings

_SETTINGS_SCHEMA_VERSION = 1


def default_application_directory() -> Path:
    """Return an OS-appropriate directory outside the source repository."""
    overridden = os.environ.get("FAMILY_SPEND_APP_DIR")
    if overridden:
        return Path(overridden)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Family Spend Tracker"
    configured = os.environ.get("XDG_CONFIG_HOME")
    base = Path(configured) if configured else Path.home() / ".config"
    return base / "family-spend-tracker"


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    """Atomically write JSON readable and writable only by the current user."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temporary:
        json.dump(value, temporary, indent=2, sort_keys=True)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.chmod(0o600)
    temporary_path.replace(path)


class FileSettingsStore:
    """Persist the workbook ID and credential reference in a private JSON file."""

    def __init__(self, path: Path) -> None:
        """Create a settings store for the supplied file path."""
        self._path = path

    def load(self) -> LocalSettings | None:
        """Load settings, returning `None` when the file does not exist."""
        if not self._path.exists():
            return None
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != _SETTINGS_SCHEMA_VERSION:
            raise ValueError("local settings schema version is incompatible")
        return LocalSettings(
            workbook_id=str(raw["workbook_id"]),
            credential_reference=str(raw["credential_reference"]),
        )

    def save(self, settings: LocalSettings) -> None:
        """Atomically save non-secret connection settings."""
        _write_private_json(
            self._path,
            {
                "schema_version": _SETTINGS_SCHEMA_VERSION,
                "workbook_id": settings.workbook_id,
                "credential_reference": settings.credential_reference,
            },
        )

    def delete(self) -> None:
        """Delete saved settings if they exist."""
        self._path.unlink(missing_ok=True)


class FileCredentialStore:
    """Persist OAuth credential JSON separately from ordinary settings."""

    def __init__(self, path: Path) -> None:
        """Create a credential store for one private file."""
        self._path = path

    @property
    def reference(self) -> str:
        """Return the non-secret reference used in local settings."""
        return str(self._path)

    def save(self, credential_data: dict[str, Any]) -> str:
        """Save credential data and return its non-secret filesystem reference."""
        _write_private_json(self._path, credential_data)
        return self.reference

    def load(self, credential_reference: str) -> dict[str, Any]:
        """Load credentials only when the reference matches this store's path."""
        if credential_reference != str(self._path):
            raise ValueError("credential reference does not match the configured store")
        if not self._path.exists():
            raise ValueError("local Google credentials were not found")
        value = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("local Google credentials are invalid")
        return value

    def delete(self, credential_reference: str) -> None:
        """Delete credentials only when the reference matches this store's path."""
        if credential_reference != str(self._path):
            raise ValueError("credential reference does not match the configured store")
        self._path.unlink(missing_ok=True)
