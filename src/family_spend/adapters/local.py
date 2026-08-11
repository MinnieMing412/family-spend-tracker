"""Local filesystem adapters for non-workbook application state."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from family_spend.domain.models import LocalSettings, StructuredCacheRecord

_SETTINGS_SCHEMA_VERSION = 1
_CACHE_SCHEMA_VERSION = 1
_CACHE_ID = re.compile(r"^[a-z0-9-]+$")


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
    path.parent.chmod(0o700)
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

    def exists(self) -> bool:
        """Return whether the credential file currently exists."""
        return self._path.exists()

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


class FileStructuredCache:
    """Persist privacy-limited structured import diagnostics in private files."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def path_for(self, cache_id: str) -> Path:
        """Return a traversal-safe cache path for diagnostics and tests."""
        if _CACHE_ID.fullmatch(cache_id) is None:
            raise ValueError("cache ID contains unsupported characters")
        return self._directory / f"{cache_id}.json"

    def load(self, cache_id: str) -> StructuredCacheRecord | None:
        """Load one cache record, returning None when it was cleaned up."""
        path = self.path_for(cache_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != _CACHE_SCHEMA_VERSION:
            raise ValueError("structured cache schema version is incompatible")
        fields = raw.get("fields")
        if not isinstance(fields, dict):
            raise ValueError("structured cache fields are invalid")
        return StructuredCacheRecord(
            cache_id=str(raw["cache_id"]),
            statement_hash=str(raw["statement_hash"]),
            fields=tuple((str(key), str(value)) for key, value in sorted(fields.items())),
        )

    def save(self, record: StructuredCacheRecord) -> None:
        """Atomically save a structured record with owner-only permissions."""
        _write_private_json(
            self.path_for(record.cache_id),
            {
                "schema_version": _CACHE_SCHEMA_VERSION,
                "cache_id": record.cache_id,
                "statement_hash": record.statement_hash,
                "fields": dict(record.fields),
            },
        )

    def delete(self, cache_id: str) -> None:
        """Delete one retained record if present."""
        self.path_for(cache_id).unlink(missing_ok=True)


class SystemClock:
    """Supply timezone-aware current UTC timestamps in production."""

    def now(self) -> datetime:
        return datetime.now(UTC)
