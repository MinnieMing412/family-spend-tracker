from __future__ import annotations

from datetime import datetime
from pathlib import Path

from family_spend.domain.models import (
    ApprovedImport,
    BackfillCheckpoint,
    CategoryConfig,
    DetectionStatus,
    ImportRecord,
    ImportResult,
    ImportStatus,
    Institution,
    InstitutionDetection,
    LocalSettings,
    NormalizedTransaction,
    ParseResult,
    ReviewState,
    StructuredCacheRecord,
    WorkbookConfig,
)
from family_spend.ports import StatementParser, ValidatedPdf
from family_spend.workbook_schema import CATEGORY_SEEDS, SCHEMA_VERSION, WORKSHEET_SCHEMAS


class StaticStatementParser:
    """Test parser that always returns one preconfigured parsing result."""

    def __init__(self, result: ParseResult) -> None:
        """Create the parser with the result it should return."""
        self._result = result

    def parse(self, source: ValidatedPdf) -> ParseResult:
        """Return the configured result without reading the supplied PDF."""
        del source
        return self._result


class StaticParserRegistry:
    """Test registry that always selects one preconfigured statement parser."""

    def __init__(self, parser: StatementParser) -> None:
        """Create the registry with the parser it should select."""
        self._parser = parser

    def parser_for(self, source: ValidatedPdf) -> StatementParser:
        """Return the configured parser for any supplied PDF."""
        del source
        return self._parser

    def detect(self, source: ValidatedPdf) -> InstitutionDetection:
        """Return a deterministic AMEX detection for fake-adapter tests."""
        del source
        return InstitutionDetection(DetectionStatus.DETECTED, (Institution.AMEX,))


class InMemorySettingsStore:
    """Keep local settings in memory for fast, isolated tests."""

    def __init__(self) -> None:
        """Create an empty settings store."""
        self._settings: LocalSettings | None = None

    def load(self) -> LocalSettings | None:
        """Return the currently stored settings, if present."""
        return self._settings

    def save(self, settings: LocalSettings) -> None:
        """Replace the currently stored settings."""
        self._settings = settings

    def delete(self) -> None:
        """Clear all stored settings."""
        self._settings = None


class InMemoryCredentialManager:
    """Simulate browser authorization without creating real credentials."""

    def __init__(self) -> None:
        """Create an empty credential manager."""
        self._references: set[str] = set()
        self._backup: set[str] | None = None

    def authorize(self, client_secrets: Path) -> str:
        """Stage a deterministic non-secret reference for the supplied file."""
        self._backup = set(self._references)
        reference = f"memory:{client_secrets.name}"
        self._references.add(reference)
        return reference

    def commit_authorization(self) -> None:
        """Accept staged in-memory credentials."""
        self._backup = None

    def rollback_authorization(self) -> None:
        """Restore credentials present before the latest authorization."""
        if self._backup is not None:
            self._references = self._backup
            self._backup = None

    def identity(self, credential_reference: str) -> str:
        """Return a deterministic identity for acceptance tests."""
        if credential_reference not in self._references:
            raise ValueError("local Google credentials were not found")
        return "Test Google account"

    def delete(self, credential_reference: str) -> None:
        """Remove a previously authorized reference."""
        self._references.discard(credential_reference)

    def contains(self, credential_reference: str) -> bool:
        """Return whether a credential reference is currently stored."""
        return credential_reference in self._references


class InMemoryWorkbookGateway:
    """Simulate workbook reads and imports without contacting Google Sheets."""

    def __init__(
        self,
        configuration: WorkbookConfig,
        *,
        workbook_id: str = "workbook-1",
    ) -> None:
        """Create an empty simulated workbook with the supplied configuration."""
        self._workbook_id = workbook_id
        self._configuration = configuration
        self._imports_by_hash: dict[str, ImportRecord] = {}
        self._transactions_by_fingerprint: dict[str, NormalizedTransaction] = {}
        self._schema_version: str | None = SCHEMA_VERSION
        self._worksheets = tuple(schema.name for schema in WORKSHEET_SCHEMAS)

    @property
    def workbook_id(self) -> str:
        """Return the simulated workbook identifier."""
        return self._workbook_id

    def provision_schema(self) -> None:
        """Provision required sheets and seed the default category taxonomy."""
        self._schema_version = SCHEMA_VERSION
        self._worksheets = tuple(schema.name for schema in WORKSHEET_SCHEMAS)
        self._configuration = WorkbookConfig(
            members=self._configuration.members,
            accounts=self._configuration.accounts,
            categories=tuple(
                CategoryConfig(
                    category_id=category.category_id,
                    display_name=category.display_name,
                    sort_order=index,
                    active=True,
                )
                for index, category in enumerate(CATEGORY_SEEDS, start=1)
            ),
            merchant_rules=self._configuration.merchant_rules,
        )

    def worksheet_names(self) -> tuple[str, ...]:
        """Return worksheet names in their provisioned order."""
        return self._worksheets

    def validate_schema(self) -> None:
        """Reject a workbook with missing or incompatible schema metadata."""
        expected = tuple(schema.name for schema in WORKSHEET_SCHEMAS)
        if self._schema_version != SCHEMA_VERSION or self._worksheets != expected:
            raise ValueError("workbook schema is missing or incompatible")

    def load_configuration(self) -> WorkbookConfig:
        """Return the workbook's members, accounts, categories, and rules."""
        return self._configuration

    def latest_successful_import(self) -> datetime | None:
        """Return the most recent completed in-memory import timestamp."""
        timestamps = tuple(
            record.imported_at
            for record in self._imports_by_hash.values()
            if record.status is ImportStatus.COMPLETE and record.imported_at is not None
        )
        return max(timestamps, default=None)

    def unresolved_exception_count(self) -> int:
        """Count imports that have not reached a completed or skipped state."""
        return sum(
            record.status in {ImportStatus.PENDING, ImportStatus.FAILED}
            for record in self._imports_by_hash.values()
        )

    def find_import_by_hash(self, statement_hash: str) -> ImportRecord | None:
        """Find a previously committed import by statement content hash."""
        return self._imports_by_hash.get(statement_hash)

    def find_transactions(
        self, fingerprints: tuple[str, ...]
    ) -> tuple[NormalizedTransaction, ...]:
        """Return committed transactions matching the requested fingerprints."""
        return tuple(
            transaction
            for fingerprint in fingerprints
            if (transaction := self._transactions_by_fingerprint.get(fingerprint)) is not None
        )

    def commit_import(self, approved_import: ApprovedImport) -> ImportResult:
        """Store an approved import once and skip duplicate statements.

        Every transaction must have a fingerprint so later imports can detect
        duplicates. A repeated statement hash returns a skipped result.
        """
        statement = approved_import.statement
        existing = self.find_import_by_hash(statement.source_hash)
        if existing is not None:
            return ImportResult(
                import_id=existing.import_id,
                status=ImportStatus.SKIPPED,
                transaction_ids=existing.transaction_ids,
                message="statement already imported",
            )

        for transaction in statement.transactions:
            if transaction.fingerprint is None:
                raise ValueError("approved transactions require a fingerprint")
            self._transactions_by_fingerprint.setdefault(transaction.fingerprint, transaction)

        transaction_ids = tuple(
            transaction.transaction_id for transaction in statement.transactions
        )
        record = ImportRecord(
            import_id=approved_import.import_id,
            statement_hash=statement.source_hash,
            status=ImportStatus.COMPLETE,
            transaction_ids=transaction_ids,
            imported_at=approved_import.reviewed_at,
        )
        self._imports_by_hash[statement.source_hash] = record
        return ImportResult(
            import_id=record.import_id,
            status=record.status,
            transaction_ids=record.transaction_ids,
            message="import complete",
        )


class InMemoryWorkbookFactory:
    """Create and connect isolated in-memory workbook gateways."""

    def __init__(self) -> None:
        """Create an empty workbook collection."""
        self._workbooks: dict[str, InMemoryWorkbookGateway] = {}
        self._next_id = 1

    def create(self, title: str) -> InMemoryWorkbookGateway:
        """Create an unprovisioned workbook with a deterministic identifier."""
        del title
        workbook_id = f"workbook-{self._next_id}"
        self._next_id += 1
        workbook = InMemoryWorkbookGateway(
            WorkbookConfig((), (), (), ()),
            workbook_id=workbook_id,
        )
        self._workbooks[workbook_id] = workbook
        return workbook

    def connect(self, workbook_id: str) -> InMemoryWorkbookGateway:
        """Return an existing workbook or fail for an unknown identifier."""
        try:
            return self._workbooks[workbook_id]
        except KeyError as error:
            raise ValueError(f"workbook not found: {workbook_id}") from error


class InMemorySheetsClient:
    """Simulate the small Google Sheets API boundary used by Phase 1."""

    def __init__(self) -> None:
        """Create an empty spreadsheet service."""
        self._workbooks: dict[str, dict[str, object]] = {}
        self._next_id = 1

    def create_workbook(self, title: str) -> str:
        """Create a workbook containing Google's default `Sheet1` worksheet."""
        workbook_id = f"google-workbook-{self._next_id}"
        self._next_id += 1
        self._workbooks[workbook_id] = {
            "title": title,
            "version": None,
            "sheets": {"Sheet1": []},
        }
        return workbook_id

    def _sheets(self, workbook_id: str) -> dict[str, list[list[object]]]:
        """Return mutable worksheet storage for one workbook."""
        workbook = self._workbooks.get(workbook_id)
        if workbook is None:
            raise ValueError(f"workbook not found: {workbook_id}")
        sheets = workbook["sheets"]
        assert isinstance(sheets, dict)
        return sheets

    def worksheet_names(self, workbook_id: str) -> tuple[str, ...]:
        """Return worksheet names in insertion order."""
        return tuple(self._sheets(workbook_id))

    def rename_worksheet(self, workbook_id: str, old_name: str, new_name: str) -> None:
        """Rename a worksheet while preserving its position and rows."""
        sheets = self._sheets(workbook_id)
        if new_name in sheets:
            raise ValueError(f"worksheet already exists: {new_name}")
        replacement: dict[str, list[list[object]]] = {}
        for name, rows in sheets.items():
            replacement[new_name if name == old_name else name] = rows
        sheets.clear()
        sheets.update(replacement)

    def add_worksheet(self, workbook_id: str, name: str) -> None:
        """Append an empty worksheet, rejecting duplicate titles."""
        sheets = self._sheets(workbook_id)
        if name in sheets:
            raise ValueError(f"worksheet already exists: {name}")
        sheets[name] = []

    def schema_version(self, workbook_id: str) -> str | None:
        """Return the workbook's schema version."""
        workbook = self._workbooks.get(workbook_id)
        if workbook is None:
            raise ValueError(f"workbook not found: {workbook_id}")
        version = workbook["version"]
        return str(version) if version is not None else None

    def set_schema_version(self, workbook_id: str, version: str) -> None:
        """Set the workbook's schema version."""
        workbook = self._workbooks.get(workbook_id)
        if workbook is None:
            raise ValueError(f"workbook not found: {workbook_id}")
        workbook["version"] = version

    def read_rows(self, workbook_id: str, worksheet: str) -> tuple[tuple[object, ...], ...]:
        """Return immutable copies of populated worksheet rows."""
        try:
            rows = self._sheets(workbook_id)[worksheet]
        except KeyError as error:
            raise ValueError(f"worksheet not found: {worksheet}") from error
        return tuple(tuple(row) for row in rows)

    def write_rows(
        self,
        workbook_id: str,
        worksheet: str,
        start_row: int,
        rows: tuple[tuple[object, ...], ...],
    ) -> None:
        """Replace worksheet rows beginning at a one-based position."""
        try:
            stored_rows = self._sheets(workbook_id)[worksheet]
        except KeyError as error:
            raise ValueError(f"worksheet not found: {worksheet}") from error
        index = start_row - 1
        while len(stored_rows) < index:
            stored_rows.append([])
        for offset, row in enumerate(rows):
            target = index + offset
            replacement = list(row)
            if target < len(stored_rows):
                stored_rows[target] = replacement
            else:
                stored_rows.append(replacement)

    def header_row_count(self, workbook_id: str, worksheet: str) -> int:
        """Return the two schema header rows when both are populated."""
        rows = self.read_rows(workbook_id, worksheet)
        return int(len(rows) >= 2 and bool(rows[0]) and bool(rows[1])) * 2


class InMemoryCheckpointStore:
    """Keep historical backfill checkpoints in memory for tests."""

    def __init__(self) -> None:
        """Create an empty checkpoint store."""
        self._checkpoints: dict[str, BackfillCheckpoint] = {}

    def load(self, root_id: str) -> BackfillCheckpoint | None:
        """Load the checkpoint for one backfill root."""
        return self._checkpoints.get(root_id)

    def save(self, checkpoint: BackfillCheckpoint) -> None:
        """Create or replace a backfill checkpoint."""
        self._checkpoints[checkpoint.root_id] = checkpoint

    def delete(self, root_id: str) -> None:
        """Remove a checkpoint when it is no longer needed."""
        self._checkpoints.pop(root_id, None)


class InMemoryStructuredCache:
    """Keep structured, non-raw parser cache records in memory."""

    def __init__(self) -> None:
        """Create an empty structured cache."""
        self._records: dict[str, StructuredCacheRecord] = {}

    def load(self, cache_id: str) -> StructuredCacheRecord | None:
        """Load a cache record by identifier."""
        return self._records.get(cache_id)

    def save(self, record: StructuredCacheRecord) -> None:
        """Create or replace a structured cache record."""
        self._records[record.cache_id] = record

    def delete(self, cache_id: str) -> None:
        """Remove a structured cache record."""
        self._records.pop(cache_id, None)


class ScriptedReviewPort:
    """Return queued review decisions for deterministic workflow tests."""

    def __init__(self, decisions: tuple[ReviewState, ...]) -> None:
        """Create a reviewer with decisions returned in first-in-first-out order."""
        self._decisions = list(decisions)

    def review(self, state: ReviewState) -> ReviewState:
        """Return the next decision, failing when the decision queue is empty."""
        del state
        if not self._decisions:
            raise RuntimeError("no scripted review decision remains")
        return self._decisions.pop(0)


class FixedClock:
    """Clock that always reports one configured time."""

    def __init__(self, current_time: datetime) -> None:
        """Create a clock fixed at `current_time`."""
        self._current_time = current_time

    def now(self) -> datetime:
        """Return the configured fixed time."""
        return self._current_time


class SequentialIdGenerator:
    """Generate predictable, increasing identifiers grouped by prefix."""

    def __init__(self) -> None:
        """Create a generator whose first value for each prefix is one."""
        self._next_values: dict[str, int] = {}

    def new_id(self, prefix: str) -> str:
        """Return the next identifier, such as `transaction-1`."""
        value = self._next_values.get(prefix, 0) + 1
        self._next_values[prefix] = value
        return f"{prefix}-{value}"
