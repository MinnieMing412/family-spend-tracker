"""Construct production adapters for the command-line application."""

from __future__ import annotations

from family_spend.adapters.google import GoogleApiSheetsClient, GoogleWorkbookFactory
from family_spend.adapters.google_auth import GoogleCredentialManager
from family_spend.adapters.local import (
    FileCheckpointStore,
    FileCredentialStore,
    FileSettingsStore,
    FileStructuredCache,
    SystemClock,
    default_application_directory,
)
from family_spend.adapters.terminal import TerminalBackfillReviewPort, TerminalReviewPort
from family_spend.application import FamilySpendApplication
from family_spend.domain.models import Institution
from family_spend.ingestion import (
    MarkerParserRegistry,
    ParserRegistration,
    PdfValidator,
    StatementIngestionService,
)
from family_spend.parsers import (
    AmexStatementParser,
    BankOfAmericaStatementParser,
    ChaseStatementParser,
)
from family_spend.review import ReviewEngine


def build_application() -> FamilySpendApplication:
    """Build the real application using private local files and Google APIs."""
    application_directory = default_application_directory()
    settings = FileSettingsStore(application_directory / "settings.json")
    credential_store = FileCredentialStore(application_directory / "credentials.json")
    credentials = GoogleCredentialManager(credential_store)
    sheets = GoogleApiSheetsClient(credential_store)
    workbooks = GoogleWorkbookFactory(sheets)
    amex_parser = AmexStatementParser()
    bank_of_america_parser = BankOfAmericaStatementParser()
    chase_parser = ChaseStatementParser()
    ingestion = StatementIngestionService(
        PdfValidator(),
        MarkerParserRegistry(
            (
                ParserRegistration(
                    institution=Institution.AMEX,
                    markers=(
                        "American Express",
                        "Account Ending",
                        "Payments and Credits",
                        "New Charges",
                    ),
                    parser=amex_parser,
                    minimum_markers=2,
                ),
                ParserRegistration(
                    institution=Institution.BANK_OF_AMERICA,
                    markers=(
                        "Bank of America",
                        "Account Summary",
                        "Payments and Other Credits",
                        "Purchases and Adjustments",
                    ),
                    parser=bank_of_america_parser,
                    minimum_markers=2,
                ),
                ParserRegistration(
                    institution=Institution.CHASE,
                    markers=(
                        "CHASE",
                        "Account Summary",
                        "Account Activity",
                        "Payments and Other Credits",
                    ),
                    parser=chase_parser,
                    minimum_markers=2,
                ),
            )
        ),
    )
    review_engine = ReviewEngine()
    return FamilySpendApplication(
        settings=settings,
        credentials=credentials,
        workbooks=workbooks,
        cache_location=application_directory / "cache",
        ingestion=ingestion,
        review_engine=review_engine,
        reviewer=TerminalReviewPort(engine=review_engine),
        structured_cache=FileStructuredCache(application_directory / "cache"),
        clock=SystemClock(),
        checkpoint_store=FileCheckpointStore(application_directory / "checkpoints"),
        backfill_reviewer=TerminalBackfillReviewPort(),
    )
