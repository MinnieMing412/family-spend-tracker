from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path

from family_spend.adapters.memory import InMemorySettingsStore
from family_spend.application import FamilySpendApplication
from family_spend.cli import main
from family_spend.domain.models import Institution
from family_spend.ingestion import (
    MarkerParserRegistry,
    ParserRegistration,
    PdfValidator,
    StatementIngestionService,
)
from family_spend.parsers import AmexStatementParser
from tests.pdf_factory import write_text_pdf

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "amex" / "synthetic_statement.txt"


def parse_application() -> FamilySpendApplication:
    parser = AmexStatementParser()
    ingestion = StatementIngestionService(
        PdfValidator(),
        MarkerParserRegistry(
            (
                ParserRegistration(
                    Institution.AMEX,
                    ("American Express", "Account Ending", "New Charges"),
                    parser,
                ),
            )
        ),
    )
    return FamilySpendApplication(
        settings=InMemorySettingsStore(),
        ingestion=ingestion,
    )


class ParseCliAcceptanceTests(unittest.TestCase):
    def test_import_detects_and_summarizes_without_uploading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statement.pdf"
            write_text_pdf(path, tuple(FIXTURE.read_text().split("\f")))
            stdout = StringIO()
            stderr = StringIO()

            exit_code = main(
                ["import", str(path)],
                application=parse_application(),
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertEqual("", stderr.getvalue())
        self.assertIn("Detected AMEX statement", stdout.getvalue())
        self.assertIn("8 transactions", stdout.getvalue())
        self.assertIn("No transactions were uploaded", stdout.getvalue())

    def test_import_directory_summarizes_recursively_discovered_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "2026" / "06"
            nested.mkdir(parents=True)
            pages = tuple(FIXTURE.read_text().split("\f"))
            write_text_pdf(root / "first.pdf", pages)
            write_text_pdf(nested / "second.pdf", pages)
            stdout = StringIO()
            stderr = StringIO()

            exit_code = main(
                ["import", str(root)],
                application=parse_application(),
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertEqual(2, stdout.getvalue().count("Detected AMEX statement"))
        self.assertEqual(1, stdout.getvalue().count("No transactions were uploaded"))
