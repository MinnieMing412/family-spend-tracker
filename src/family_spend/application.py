from __future__ import annotations

from typing import Protocol

from family_spend.ports import SettingsStore, WorkbookGateway


class CliApplication(Protocol):
    """Operations the command-line interface can request from the application."""

    def status(self) -> str:
        """Return a short, human-readable summary of the current connection."""
        ...


class FamilySpendApplication:
    """Coordinate CLI requests using settings and workbook storage boundaries."""

    def __init__(self, *, settings: SettingsStore, workbook: WorkbookGateway) -> None:
        """Create the application with its local settings and workbook providers."""
        self._settings = settings
        self._workbook = workbook

    def status(self) -> str:
        """Describe the connected workbook, or explain that none is connected."""
        settings = self._settings.load()
        if settings is None:
            return "No workbook is connected."

        self._workbook.validate_schema()
        configuration = self._workbook.load_configuration()
        return (
            f"Connected workbook {settings.workbook_id}: "
            f"{len(configuration.members)} members, "
            f"{len(configuration.accounts)} accounts."
        )
