from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlparse

from family_spend.domain.models import LocalSettings, ReviewStatus
from family_spend.imports import SingleImportWorkflow
from family_spend.ingestion import StatementIngestionService, discover_pdfs
from family_spend.ports import (
    Clock,
    CredentialManager,
    ReviewPort,
    SettingsStore,
    StructuredCache,
    WorkbookConnection,
    WorkbookFactory,
    WorkbookGateway,
)
from family_spend.review import ReviewEngine


def _workbook_id_from_url(workbook_url: str) -> str:
    """Extract a Google spreadsheet ID from its standard browser URL."""
    parsed = urlparse(workbook_url)
    if parsed.scheme != "https" or parsed.hostname != "docs.google.com":
        raise ValueError("workbook URL must use https://docs.google.com")
    path_parts = parsed.path.strip("/").split("/")
    if len(path_parts) < 3 or path_parts[:2] != ["spreadsheets", "d"] or not path_parts[2]:
        raise ValueError("workbook URL must be a Google Sheets spreadsheet URL")
    return path_parts[2]


class CliApplication(Protocol):
    """Operations the command-line interface can request from the application."""

    def status(self) -> str:
        """Return a short, human-readable summary of the current connection."""
        ...

    def setup(
        self,
        *,
        client_secrets: Path,
        workbook_name: str,
        workbook_url: str | None,
    ) -> str:
        """Authorize Google and create or connect a compatible workbook."""
        ...

    def validate_workbook(self) -> str:
        """Validate the connected workbook and return a user-facing result."""
        ...

    def disconnect(self) -> str:
        """Remove local credentials and connection settings."""
        ...

    def parse_summary(self, source: Path) -> str:
        """Parse statement PDFs and summarize them without uploading data."""
        ...

    def import_statement(self, source: Path, *, retain_cache: bool = False) -> str:
        """Parse, review, and import exactly one statement PDF."""
        ...


class FamilySpendApplication:
    """Coordinate CLI requests using settings and workbook storage boundaries."""

    def __init__(
        self,
        *,
        settings: SettingsStore,
        workbook: WorkbookConnection | None = None,
        credentials: CredentialManager | None = None,
        workbooks: WorkbookFactory | None = None,
        cache_location: Path | None = None,
        ingestion: StatementIngestionService | None = None,
        review_engine: ReviewEngine | None = None,
        reviewer: ReviewPort | None = None,
        structured_cache: StructuredCache | None = None,
        clock: Clock | None = None,
    ) -> None:
        """Create the application with its local settings and workbook providers."""
        self._settings = settings
        self._workbook = workbook
        self._credentials = credentials
        self._workbooks = workbooks
        self._cache_location = cache_location
        self._ingestion = ingestion
        self._review_engine = review_engine
        self._reviewer = reviewer
        self._structured_cache = structured_cache
        self._clock = clock

    def setup(
        self,
        *,
        client_secrets: Path,
        workbook_name: str,
        workbook_url: str | None,
    ) -> str:
        """Authorize Google, provision a workbook, and save its local reference."""
        if self._credentials is None or self._workbooks is None:
            raise ValueError("setup dependencies are not configured")

        credential_reference = self._credentials.authorize(client_secrets)
        try:
            if workbook_url is None:
                workbook = self._workbooks.create(workbook_name)
                workbook.provision_schema()
                workbook.validate_schema()
            else:
                workbook = self._workbooks.connect(_workbook_id_from_url(workbook_url))
                workbook.validate_schema()
            self._settings.save(
                LocalSettings(
                    workbook_id=workbook.workbook_id,
                    credential_reference=credential_reference,
                )
            )
        except Exception:
            self._credentials.rollback_authorization()
            raise
        self._credentials.commit_authorization()
        categories = ", ".join(
            category.display_name for category in workbook.load_configuration().categories
        )
        return f"Connected workbook {workbook.workbook_id}. Seeded categories: {categories}."

    def status(self) -> str:
        """Describe the connected workbook, or explain that none is connected."""
        settings = self._settings.load()
        if settings is None:
            return "No workbook is connected."

        workbook = (
            self._workbooks.connect(settings.workbook_id)
            if self._workbooks is not None
            else self._workbook
        )
        if workbook is None:
            raise ValueError("workbook dependency is not configured")
        workbook.validate_schema()
        configuration = workbook.load_configuration()
        identity = (
            self._credentials.identity(settings.credential_reference)
            if self._credentials is not None
            else "unavailable"
        )
        latest_import = workbook.latest_successful_import()
        latest_import_text = latest_import.isoformat() if latest_import is not None else "none"
        unresolved_exceptions = workbook.unresolved_exception_count()
        cache_text = str(self._cache_location) if self._cache_location is not None else "none"
        return (
            f"Connected workbook {settings.workbook_id}: "
            f"{len(configuration.members)} members, "
            f"{len(configuration.accounts)} accounts.\n"
            f"Authenticated Google identity: {identity}\n"
            f"Last successful import: {latest_import_text}\n"
            f"Unresolved exceptions: {unresolved_exceptions}\n"
            f"Retained cache location: {cache_text}"
        )

    def validate_workbook(self) -> str:
        """Confirm that the connected workbook matches the supported schema."""
        settings = self._settings.load()
        if settings is None:
            raise ValueError("no workbook is connected")
        if self._workbooks is None:
            raise ValueError("workbook factory is not configured")
        workbook = self._workbooks.connect(settings.workbook_id)
        workbook.validate_schema()
        return f"Workbook {settings.workbook_id} is compatible."

    def disconnect(self) -> str:
        """Remove local credentials and settings without deleting the workbook."""
        settings = self._settings.load()
        if settings is None:
            return "No local Google connection was found."
        if self._credentials is None:
            raise ValueError("credential manager is not configured")
        self._credentials.delete(settings.credential_reference)
        self._settings.delete()
        return "Local Google access removed. The Google workbook was not deleted."

    def parse_summary(self, source: Path) -> str:
        """Validate, detect, and parse statements without workbook writes."""
        if self._ingestion is None:
            raise ValueError("statement ingestion is not configured")
        return self._ingestion.parse_summary(source)

    def import_statement(self, source: Path, *, retain_cache: bool = False) -> str:
        """Parse, review, and idempotently import one statement when configured."""
        if self._review_engine is None or self._reviewer is None:
            return self.parse_summary(source)
        if self._ingestion is None:
            raise ValueError("statement ingestion is not configured")
        paths = discover_pdfs(source)
        if len(paths) != 1:
            raise ValueError("single import accepts exactly one statement PDF")
        settings = self._settings.load()
        if settings is None:
            raise ValueError("no workbook is connected")
        if self._workbooks is not None:
            workbook = self._workbooks.connect(settings.workbook_id)
        elif self._workbook is not None:
            workbook = self._workbook
        else:
            raise ValueError("workbook dependency is not configured")
        if self._structured_cache is not None and self._clock is not None:
            outcome = SingleImportWorkflow(
                ingestion=self._ingestion,
                review_engine=self._review_engine,
                reviewer=self._reviewer,
                workbook=cast(WorkbookGateway, workbook),
                configuration=workbook.load_configuration(),
                cache=self._structured_cache,
                clock=self._clock,
            ).execute(paths[0], retain_cache=retain_cache)
            cache_text = (
                f" Retained cache: {outcome.cache_id}." if outcome.cache_id else ""
            )
            duplicate_text = (
                f" Exact duplicates skipped: {outcome.exact_duplicate_count}."
                if outcome.exact_duplicate_count
                else ""
            )
            return f"{outcome.message}{duplicate_text}{cache_text}"
        results = self._ingestion.parse(paths[0])
        initial = self._review_engine.prepare(
            results[0].statement,
            workbook.load_configuration(),
        )
        decision = self._reviewer.review(initial)
        if decision.statement.statement_id != initial.statement.statement_id:
            raise ValueError("review decision does not belong to the parsed statement")
        if decision.status is ReviewStatus.PENDING:
            raise ValueError("review must explicitly approve or cancel")
        if decision.status is ReviewStatus.CANCELLED:
            return "Review cancelled. No transactions were uploaded."
        return (
            f"Review approved for {len(decision.rows)} transactions; "
            f"{len(decision.saved_rules)} merchant rules selected. "
            "No transactions were uploaded."
        )
