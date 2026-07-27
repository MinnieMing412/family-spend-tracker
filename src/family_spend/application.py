from __future__ import annotations

from typing import Protocol

from family_spend.ports import SettingsStore, WorkbookGateway


class CliApplication(Protocol):
    def status(self) -> str: ...


class FamilySpendApplication:
    def __init__(self, *, settings: SettingsStore, workbook: WorkbookGateway) -> None:
        self._settings = settings
        self._workbook = workbook

    def status(self) -> str:
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
