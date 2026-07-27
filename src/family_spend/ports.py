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
    path: Path
    source_name: str
    sha256: str
    page_count: int


class StatementParser(Protocol):
    def parse(self, source: ValidatedPdf) -> ParseResult: ...


class ParserRegistry(Protocol):
    def parser_for(self, source: ValidatedPdf) -> StatementParser: ...


class SettingsStore(Protocol):
    def load(self) -> LocalSettings | None: ...

    def save(self, settings: LocalSettings) -> None: ...

    def delete(self) -> None: ...


class WorkbookGateway(Protocol):
    def validate_schema(self) -> None: ...

    def load_configuration(self) -> WorkbookConfig: ...

    def find_import_by_hash(self, statement_hash: str) -> ImportRecord | None: ...

    def find_transactions(
        self, fingerprints: tuple[str, ...]
    ) -> tuple[NormalizedTransaction, ...]: ...

    def commit_import(self, approved_import: ApprovedImport) -> ImportResult: ...


class ReviewPort(Protocol):
    def review(self, state: ReviewState) -> ReviewState: ...


class CheckpointStore(Protocol):
    def load(self, root_id: str) -> BackfillCheckpoint | None: ...

    def save(self, checkpoint: BackfillCheckpoint) -> None: ...

    def delete(self, root_id: str) -> None: ...


class StructuredCache(Protocol):
    def load(self, cache_id: str) -> StructuredCacheRecord | None: ...

    def save(self, record: StructuredCacheRecord) -> None: ...

    def delete(self, cache_id: str) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self, prefix: str) -> str: ...
