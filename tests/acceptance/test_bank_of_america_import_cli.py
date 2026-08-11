from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path

from family_spend.adapters.memory import (
    FixedClock,
    InMemorySettingsStore,
    InMemoryStructuredCache,
    InMemoryWorkbookGateway,
)
from family_spend.application import FamilySpendApplication
from family_spend.cli import main
from family_spend.domain.models import (
    AccountConfig,
    CategoryConfig,
    Institution,
    LocalSettings,
    MemberConfig,
    WorkbookConfig,
)
from family_spend.ingestion import (
    MarkerParserRegistry,
    ParserRegistration,
    PdfValidator,
    StatementIngestionService,
)
from family_spend.parsers import AmexStatementParser, BankOfAmericaStatementParser
from family_spend.review import ReviewEngine
from tests.import_helpers import ApprovingReviewer, CancellingReviewer
from tests.pdf_factory import write_text_pdf

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "bank_of_america"
    / "synthetic_credit_card_statement.txt"
)


def build_ingestion() -> StatementIngestionService:
    return StatementIngestionService(
        PdfValidator(),
        MarkerParserRegistry(
            (
                ParserRegistration(
                    Institution.AMEX,
                    ("American Express", "Account Ending", "New Charges"),
                    AmexStatementParser(),
                ),
                ParserRegistration(
                    Institution.BANK_OF_AMERICA,
                    (
                        "Bank of America",
                        "Account Summary",
                        "Payments and Other Credits",
                        "Purchases and Adjustments",
                    ),
                    BankOfAmericaStatementParser(),
                    minimum_markers=2,
                ),
            )
        ),
    )


def workbook_configuration() -> WorkbookConfig:
    return WorkbookConfig(
        members=(MemberConfig("member-alpha", "Alpha", ("MEMBER ALPHA",), True),),
        accounts=(
            AccountConfig(
                "boa-primary",
                Institution.BANK_OF_AMERICA,
                "ending-4321",
                "member-alpha",
                "BOA",
                True,
            ),
        ),
        categories=(
            CategoryConfig("uncategorized", "Uncategorized", 1, True),
            CategoryConfig("other", "Other", 2, True),
        ),
        merchant_rules=(),
    )


class BankOfAmericaImportCliAcceptanceTests(unittest.TestCase):
    @staticmethod
    def _application(
        workbook: InMemoryWorkbookGateway,
        engine: ReviewEngine,
        reviewer: ApprovingReviewer | CancellingReviewer,
        cache: InMemoryStructuredCache,
    ) -> FamilySpendApplication:
        settings = InMemorySettingsStore()
        settings.save(LocalSettings("workbook-1", "memory:credentials"))
        return FamilySpendApplication(
            settings=settings,
            workbook=workbook,
            ingestion=build_ingestion(),
            review_engine=engine,
            reviewer=reviewer,
            structured_cache=cache,
            clock=FixedClock(datetime(2026, 8, 10, 12, 0, tzinfo=UTC)),
        )

    @staticmethod
    def _run(
        application: FamilySpendApplication,
        path: Path,
    ) -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = main(
            ["import", str(path)],
            application=application,
            stdout=stdout,
            stderr=stderr,
        )
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_boa_statement_imports_once_through_the_shared_workflow(self) -> None:
        engine = ReviewEngine()
        reviewer = ApprovingReviewer(engine)
        workbook = InMemoryWorkbookGateway(workbook_configuration())
        cache = InMemoryStructuredCache()
        application = self._application(workbook, engine, reviewer, cache)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unhelpful-name.pdf"
            write_text_pdf(path, tuple(FIXTURE.read_text().split("\f")))
            statement_hash = hashlib.sha256(path.read_bytes()).hexdigest()

            first = self._run(application, path)
            repeated = self._run(application, path)

        transactions = workbook.transactions_in_window("ending-4321", date.min, date.max)
        self.assertEqual((0, ""), (first[0], first[2]))
        self.assertIn("import complete", first[1])
        self.assertEqual((0, ""), (repeated[0], repeated[2]))
        self.assertIn("already imported", repeated[1])
        self.assertEqual(1, reviewer.call_count)
        self.assertEqual(7, len(transactions))
        self.assertTrue(
            all(item.institution is Institution.BANK_OF_AMERICA for item in transactions)
        )
        self.assertIsNotNone(workbook.find_import_by_hash(statement_hash))
        self.assertIsNone(cache.load(f"cache-{statement_hash[:20]}"))

    def test_boa_statement_is_detected_in_parse_only_mode(self) -> None:
        application = FamilySpendApplication(
            settings=InMemorySettingsStore(),
            ingestion=build_ingestion(),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-named-after-a-bank.pdf"
            write_text_pdf(path, tuple(FIXTURE.read_text().split("\f")))

            result = self._run(application, path)

        self.assertEqual((0, ""), (result[0], result[2]))
        self.assertIn("Detected BANK OF AMERICA statement", result[1])
        self.assertIn("7 transactions", result[1])
        self.assertIn("No transactions were uploaded", result[1])

    def test_boa_cancel_uses_the_shared_no_write_guarantee(self) -> None:
        engine = ReviewEngine()
        workbook = InMemoryWorkbookGateway(workbook_configuration())
        cache = InMemoryStructuredCache()
        application = self._application(
            workbook,
            engine,
            CancellingReviewer(engine),
            cache,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statement.pdf"
            write_text_pdf(path, tuple(FIXTURE.read_text().split("\f")))
            statement_hash = hashlib.sha256(path.read_bytes()).hexdigest()

            result = self._run(application, path)

        self.assertEqual((0, ""), (result[0], result[2]))
        self.assertIn("Review cancelled", result[1])
        self.assertEqual(
            (),
            workbook.transactions_in_window("ending-4321", date.min, date.max),
        )
        self.assertIsNone(workbook.find_import_by_hash(statement_hash))
        self.assertIsNone(cache.load(f"cache-{statement_hash[:20]}"))


if __name__ == "__main__":
    unittest.main()
