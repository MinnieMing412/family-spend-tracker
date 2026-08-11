"""Construct production adapters for the command-line application."""

from __future__ import annotations

from family_spend.adapters.google import GoogleApiSheetsClient, GoogleWorkbookFactory
from family_spend.adapters.google_auth import GoogleCredentialManager
from family_spend.adapters.local import (
    FileCredentialStore,
    FileSettingsStore,
    default_application_directory,
)
from family_spend.application import FamilySpendApplication


def build_application() -> FamilySpendApplication:
    """Build the real application using private local files and Google APIs."""
    application_directory = default_application_directory()
    settings = FileSettingsStore(application_directory / "settings.json")
    credential_store = FileCredentialStore(application_directory / "credentials.json")
    credentials = GoogleCredentialManager(credential_store)
    sheets = GoogleApiSheetsClient(credential_store)
    workbooks = GoogleWorkbookFactory(sheets)
    return FamilySpendApplication(
        settings=settings,
        credentials=credentials,
        workbooks=workbooks,
        cache_location=application_directory / "cache",
    )
