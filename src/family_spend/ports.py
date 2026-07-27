from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from family_spend.domain.models import (
    ApprovedImport,
    BackfillCheckpoint,
    ImportRecord,
    ImportResult,
    LocalSettings,
    NormalizedTransaction,
    ParseResult,
    ReviewState,
    StructuredCacheRecord,
    WorkbookConfig,
)


class ValidatedPdf(Protocol):
    """Metadata for a PDF that has already passed basic file validation."""

    path: Path
    source_name: str
    sha256: str
    page_count: int


class StatementParser(Protocol):
    """Convert one supported bank statement PDF into normalized records."""

    def parse(self, source: ValidatedPdf) -> ParseResult:
        """Parse a validated PDF and return its statement plus any warnings."""
        ...


class ParserRegistry(Protocol):
    """Select the correct institution-specific parser for a statement."""

    def parser_for(self, source: ValidatedPdf) -> StatementParser:
        """Return a parser that supports the supplied PDF."""
        ...


class SettingsStore(Protocol):
    """Persist the local pointer to a connected Google Sheets workbook."""

    def load(self) -> LocalSettings | None:
        """Load saved settings, returning `None` when setup has not run."""
        ...

    def save(self, settings: LocalSettings) -> None:
        """Store the workbook and credential references for future commands."""
        ...

    def delete(self) -> None:
        """Remove locally saved connection settings."""
        ...


class CredentialManager(Protocol):
    """Authorize Google access and remove locally retained credentials."""

    def authorize(self, client_secrets: Path) -> str:
        """Stage browser authorization and return a non-secret local reference."""
        ...

    def commit_authorization(self) -> None:
        """Accept staged credentials after setup succeeds."""
        ...

    def rollback_authorization(self) -> None:
        """Restore previous credentials after setup fails."""
        ...

    def identity(self, credential_reference: str) -> str:
        """Return the authenticated Google identity for status output."""
        ...

    def delete(self, credential_reference: str) -> None:
        """Delete the credentials identified by the local reference."""
        ...


class WorkbookConnection(Protocol):
    """Provision and read one compatible Google Sheets workbook."""

    @property
    def workbook_id(self) -> str:
        """Return the identifier of the connected Google workbook."""
        ...

    def provision_schema(self) -> None:
        """Create missing required sheets, headers, metadata, and categories."""
        ...

    def validate_schema(self) -> None:
        """Raise an error when required sheets or columns are missing."""
        ...

    def load_configuration(self) -> WorkbookConfig:
        """Load members, accounts, categories, and merchant rules."""
        ...

    def latest_successful_import(self) -> datetime | None:
        """Return the newest successful import timestamp, if one exists."""
        ...

class WorkbookGateway(WorkbookConnection, Protocol):
    """Extend a workbook connection with Phase 4 transaction import operations."""

    def find_import_by_hash(self, statement_hash: str) -> ImportRecord | None:
        """Find a prior import of the same statement, if one exists."""
        ...

    def find_transactions(
        self, fingerprints: tuple[str, ...]
    ) -> tuple[NormalizedTransaction, ...]:
        """Return existing transactions matching the supplied fingerprints."""
        ...

    def commit_import(self, approved_import: ApprovedImport) -> ImportResult:
        """Atomically store an approved statement and its transactions."""
        ...


class WorkbookFactory(Protocol):
    """Create or connect workbook gateways after Google authorization."""

    def create(self, title: str) -> WorkbookConnection:
        """Create a new workbook and return its bound gateway."""
        ...

    def connect(self, workbook_id: str) -> WorkbookConnection:
        """Return a gateway bound to an existing workbook."""
        ...


class ReviewPort(Protocol):
    """Present parsed transactions for bulk approval and exception review."""

    def review(self, state: ReviewState) -> ReviewState:
        """Collect a user's review decision and return the updated state."""
        ...


class CheckpointStore(Protocol):
    """Persist progress so a historical backfill can resume safely."""

    def load(self, root_id: str) -> BackfillCheckpoint | None:
        """Load progress for one backfill root, if it was previously started."""
        ...

    def save(self, checkpoint: BackfillCheckpoint) -> None:
        """Save the latest completed and failed statements for a backfill."""
        ...

    def delete(self, root_id: str) -> None:
        """Delete saved progress after completion or at the user's request."""
        ...


class StructuredCache(Protocol):
    """Store structured parser data without retaining raw PDF text."""

    def load(self, cache_id: str) -> StructuredCacheRecord | None:
        """Load a structured cache record by its identifier."""
        ...

    def save(self, record: StructuredCacheRecord) -> None:
        """Save structured parser output for reuse or troubleshooting."""
        ...

    def delete(self, cache_id: str) -> None:
        """Delete a structured cache record."""
        ...


class Clock(Protocol):
    """Supply the current time while allowing deterministic tests."""

    def now(self) -> datetime:
        """Return the current date and time."""
        ...


class IdGenerator(Protocol):
    """Create identifiers for transactions, statements, and imports."""

    def new_id(self, prefix: str) -> str:
        """Return a new identifier beginning with the requested prefix."""
        ...
