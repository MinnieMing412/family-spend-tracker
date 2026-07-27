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
    def __init__(self, result: ParseResult) -> None:
        self._result = result

    def parse(self, source: ValidatedPdf) -> ParseResult:
        del source
        return self._result


class StaticParserRegistry:
    def __init__(self, parser: StatementParser) -> None:
        self._parser = parser

    def parser_for(self, source: ValidatedPdf) -> StatementParser:
        del source
        return self._parser


class InMemorySettingsStore:
    def __init__(self) -> None:
        self._settings: LocalSettings | None = None

    def load(self) -> LocalSettings | None:
        return self._settings

    def save(self, settings: LocalSettings) -> None:
        self._settings = settings

    def delete(self) -> None:
        self._settings = None


class InMemoryWorkbookGateway:
    def __init__(self, configuration: WorkbookConfig) -> None:
        self._configuration = configuration
        self._imports_by_hash: dict[str, ImportRecord] = {}
        self._transactions_by_fingerprint: dict[str, NormalizedTransaction] = {}

    def validate_schema(self) -> None:
        return None

    def load_configuration(self) -> WorkbookConfig:
        return self._configuration

    def find_import_by_hash(self, statement_hash: str) -> ImportRecord | None:
        return self._imports_by_hash.get(statement_hash)

    def find_transactions(
        self, fingerprints: tuple[str, ...]
    ) -> tuple[NormalizedTransaction, ...]:
        return tuple(
            transaction
            for fingerprint in fingerprints
            if (transaction := self._transactions_by_fingerprint.get(fingerprint)) is not None
        )

    def commit_import(self, approved_import: ApprovedImport) -> ImportResult:
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
    def __init__(self) -> None:
        self._checkpoints: dict[str, BackfillCheckpoint] = {}

    def load(self, root_id: str) -> BackfillCheckpoint | None:
        return self._checkpoints.get(root_id)

    def save(self, checkpoint: BackfillCheckpoint) -> None:
        self._checkpoints[checkpoint.root_id] = checkpoint

    def delete(self, root_id: str) -> None:
        self._checkpoints.pop(root_id, None)


class InMemoryStructuredCache:
    def __init__(self) -> None:
        self._records: dict[str, StructuredCacheRecord] = {}

    def load(self, cache_id: str) -> StructuredCacheRecord | None:
        return self._records.get(cache_id)

    def save(self, record: StructuredCacheRecord) -> None:
        self._records[record.cache_id] = record

    def delete(self, cache_id: str) -> None:
        self._records.pop(cache_id, None)


class ScriptedReviewPort:
    def __init__(self, decisions: tuple[ReviewState, ...]) -> None:
        self._decisions = list(decisions)

    def review(self, state: ReviewState) -> ReviewState:
        del state
        if not self._decisions:
            raise RuntimeError("no scripted review decision remains")
        return self._decisions.pop(0)


class FixedClock:
    def __init__(self, current_time: datetime) -> None:
        self._current_time = current_time

    def now(self) -> datetime:
        return self._current_time


class SequentialIdGenerator:
    def __init__(self) -> None:
        self._next_values: dict[str, int] = {}

    def new_id(self, prefix: str) -> str:
        value = self._next_values.get(prefix, 0) + 1
        self._next_values[prefix] = value
        return f"{prefix}-{value}"
