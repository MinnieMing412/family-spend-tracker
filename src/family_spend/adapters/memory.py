from __future__ import annotations

from datetime import datetime

from family_spend.domain.models import (
    ApprovedImport,
    BackfillCheckpoint,
    ImportRecord,
    ImportResult,
    ImportStatus,
    LocalSettings,
    NormalizedTransaction,
    ParseResult,
    ReviewState,
    StructuredCacheRecord,
    WorkbookConfig,
)
from family_spend.ports import StatementParser, ValidatedPdf


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


class InMemoryWorkbookGateway:
    """Simulate workbook reads and imports without contacting Google Sheets."""

    def __init__(self, configuration: WorkbookConfig) -> None:
        """Create an empty simulated workbook with the supplied configuration."""
        self._configuration = configuration
        self._imports_by_hash: dict[str, ImportRecord] = {}
        self._transactions_by_fingerprint: dict[str, NormalizedTransaction] = {}

    def validate_schema(self) -> None:
        """Accept the in-memory workbook as structurally valid."""
        return None

    def load_configuration(self) -> WorkbookConfig:
        """Return the workbook's members, accounts, categories, and rules."""
        return self._configuration

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
