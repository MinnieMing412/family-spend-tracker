from __future__ import annotations

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
from family_spend.parsers import ChaseStatementParser
from family_spend.review import ReviewEngine
from tests.import_helpers import ApprovingReviewer, CancellingReviewer
from tests.pdf_factory import write_text_pdf

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "chase"
    / "synthetic_credit_card_statement.txt"
)


def build_ingestion() -> StatementIngestionService:
    return StatementIngestionService(
        PdfValidator(),
        MarkerParserRegistry(
            (
                ParserRegistration(
                    Institution.CHASE,
                    (
                        "CHASE",
                        "Account Summary",
                        "Account Activity",
                        "Payments and Other Credits",
                    ),
                    ChaseStatementParser(),
                    minimum_markers=2,
                ),
            )
        ),
    )


def workbook_configuration() -> WorkbookConfig:
    return WorkbookConfig(
        members=(MemberConfig("member-owner", "Owner", (), True),),
        accounts=(
            AccountConfig(
                "chase-primary",
                Institution.CHASE,
                "ending-9174",
                "member-owner",
                "Chase",
                True,
            ),
        ),
        categories=(
            CategoryConfig("uncategorized", "Uncategorized", 1, True),
            CategoryConfig("other", "Other", 2, True),
        ),
        merchant_rules=(),
    )


class ChaseImportCliAcceptanceTests(unittest.TestCase):
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
            clock=FixedClock(datetime(2026, 8, 29, 12, 0, tzinfo=UTC)),
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

    def test_chase_statement_imports_once_through_the_shared_workflow(self) -> None:
        engine = ReviewEngine()
        reviewer = ApprovingReviewer(engine)
        workbook = InMemoryWorkbookGateway(workbook_configuration())
        cache = InMemoryStructuredCache()
        application = self._application(workbook, engine, reviewer, cache)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unhelpful.pdf"
            write_text_pdf(path, tuple(FIXTURE.read_text().split("\f")))

            first = self._run(application, path)
            repeated = self._run(application, path)

        transactions = workbook.transactions_in_window("ending-9174", date.min, date.max)
        self.assertEqual((0, ""), (first[0], first[2]))
        self.assertIn("import complete", first[1])
        self.assertEqual((0, ""), (repeated[0], repeated[2]))
        self.assertIn("already imported", repeated[1])
        self.assertEqual(1, reviewer.call_count)
        self.assertEqual(6, len(transactions))
        self.assertEqual(5, sum(item.included_in_spend for item in transactions))
        self.assertTrue(all(item.source_metadata == () for item in transactions))

    def test_chase_parse_only_detection_and_cancel_no_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statement.pdf"
            write_text_pdf(path, tuple(FIXTURE.read_text().split("\f")))
            parse_only = FamilySpendApplication(
                settings=InMemorySettingsStore(),
                ingestion=build_ingestion(),
            )

            parsed = self._run(parse_only, path)

            engine = ReviewEngine()
            workbook = InMemoryWorkbookGateway(workbook_configuration())
            cancelled = self._run(
                self._application(
                    workbook,
                    engine,
                    CancellingReviewer(engine),
                    InMemoryStructuredCache(),
                ),
                path,
            )

        self.assertEqual((0, ""), (parsed[0], parsed[2]))
        self.assertIn("Detected CHASE statement", parsed[1])
        self.assertIn("6 transactions", parsed[1])
        self.assertEqual((0, ""), (cancelled[0], cancelled[2]))
        self.assertIn("Review cancelled", cancelled[1])
        self.assertEqual(
            (),
            workbook.transactions_in_window("ending-9174", date.min, date.max),
        )


if __name__ == "__main__":
    unittest.main()
