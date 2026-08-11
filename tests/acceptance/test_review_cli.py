from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path

from family_spend.adapters.memory import InMemorySettingsStore, InMemoryWorkbookGateway
from family_spend.application import FamilySpendApplication
from family_spend.cli import main
from family_spend.domain.models import (
    AccountConfig,
    CategoryConfig,
    Institution,
    LocalSettings,
    MemberConfig,
    ReviewState,
    ReviewStatus,
    WorkbookConfig,
)
from family_spend.ingestion import (
    MarkerParserRegistry,
    ParserRegistration,
    PdfValidator,
    StatementIngestionService,
)
from family_spend.parsers import AmexStatementParser
from family_spend.review import ReviewEngine
from tests.pdf_factory import write_text_pdf

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "amex" / "synthetic_statement.txt"


class CancellingReviewer:
    def __init__(self, engine: ReviewEngine) -> None:
        self._engine = engine

    def review(self, state: ReviewState) -> ReviewState:
        return self._engine.decide(state, status=ReviewStatus.CANCELLED)


class ReviewCliAcceptanceTests(unittest.TestCase):
    def test_cancel_uploads_nothing(self) -> None:
        config = WorkbookConfig(
            members=(
                MemberConfig("member-alpha", "Alpha", ("MEMBER ALPHA",), True),
                MemberConfig("member-beta", "Beta", ("MEMBER BETA",), True),
            ),
            accounts=(
                AccountConfig(
                    "amex-primary",
                    Institution.AMEX,
                    "ending-10005",
                    "member-alpha",
                    "AMEX",
                    True,
                ),
            ),
            categories=(CategoryConfig("uncategorized", "Uncategorized", 1, True),),
            merchant_rules=(),
        )
        workbook = InMemoryWorkbookGateway(config)
        settings = InMemorySettingsStore()
        settings.save(LocalSettings("workbook-1", "memory:credentials"))
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
        engine = ReviewEngine()
        application = FamilySpendApplication(
            settings=settings,
            workbook=workbook,
            ingestion=ingestion,
            review_engine=engine,
            reviewer=CancellingReviewer(engine),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statement.pdf"
            write_text_pdf(path, tuple(FIXTURE.read_text().split("\f")))
            stdout = StringIO()
            stderr = StringIO()

            exit_code = main(
                ["import", str(path)],
                application=application,
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertIn("Review cancelled", stdout.getvalue())
        self.assertIn("No transactions were uploaded", stdout.getvalue())
        self.assertIsNone(workbook.find_import_by_hash("a" * 64))
