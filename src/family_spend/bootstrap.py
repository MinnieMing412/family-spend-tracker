"""Construct production adapters for the command-line application."""

from __future__ import annotations

from family_spend.adapters.google import GoogleApiSheetsClient, GoogleWorkbookFactory
from family_spend.adapters.google_auth import GoogleCredentialManager
from family_spend.adapters.local import (
    FileCredentialStore,
    FileSettingsStore,
    default_application_directory,
)
from family_spend.adapters.terminal import TerminalReviewPort
from family_spend.application import FamilySpendApplication
from family_spend.domain.models import Institution
from family_spend.ingestion import (
    MarkerParserRegistry,
    ParserRegistration,
    PdfValidator,
    StatementIngestionService,
)
from family_spend.parsers import AmexStatementParser
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
    )
