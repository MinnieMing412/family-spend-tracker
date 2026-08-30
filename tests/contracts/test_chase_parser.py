from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from family_spend.domain.models import DetectionStatus, Institution, ReconciliationStatus
from family_spend.errors import FamilySpendError
from family_spend.ingestion import (
    MarkerParserRegistry,
    ParserRegistration,
    PdfValidator,
    ValidatedPdfDocument,
)
from family_spend.parsers import ChaseStatementParser
from family_spend.review import reconcile_statement
from tests.pdf_factory import write_text_pdf

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "chase"


def fixture_pages() -> tuple[str, ...]:
    return tuple(
        (FIXTURE_ROOT / "synthetic_credit_card_statement.txt").read_text().split("\f")
    )


def chase_registry() -> MarkerParserRegistry:
    return MarkerParserRegistry(
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
    )


class ChaseParserContractTests(unittest.TestCase):
    def test_detects_chase_from_content_not_filename(self) -> None:
        source = ValidatedPdfDocument(
            Path("unhelpful.pdf"),
            "unhelpful.pdf",
            "a" * 64,
            2,
            ("CHASE\nACCOUNT SUMMARY\nACCOUNT ACTIVITY", ""),
        )

        detection = chase_registry().detect(source)

        self.assertEqual(DetectionStatus.DETECTED, detection.status)
        self.assertEqual((Institution.CHASE,), detection.institutions)

    def test_synthetic_statement_matches_expected_contract_and_reconciles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.pdf"
            write_text_pdf(path, fixture_pages())
            source = PdfValidator().validate(path)
            expected = json.loads(
                (FIXTURE_ROOT / "synthetic_credit_card_statement.expected.json").read_text()
            )

            statement = ChaseStatementParser().parse(source).statement

        self.assertEqual(Institution.CHASE, statement.institution)
        self.assertEqual(expected["account_id"], statement.account_id)
        self.assertEqual(expected["start_date"], statement.start_date.isoformat())
        self.assertEqual(expected["end_date"], statement.end_date.isoformat())
        self.assertEqual(expected["closing_date"], statement.closing_date.isoformat())
        self.assertEqual(expected["transaction_count"], len(statement.transactions))
        self.assertEqual(
            expected["transactions"],
            [
                [
                    item.transaction_date.isoformat(),
                    item.transaction_type.value,
                    str(item.amount.amount),
                ]
                for item in statement.transactions
            ],
        )
        self.assertEqual(
            expected["reported_totals"],
            {item.section: str(item.amount.amount) for item in statement.reported_totals},
        )
        self.assertEqual(ReconciliationStatus.MATCHED, reconcile_statement(statement).status)

    def test_continuation_lines_do_not_leak_order_identifiers(self) -> None:
        source = ValidatedPdfDocument(
            Path("synthetic.pdf"),
            "synthetic.pdf",
            "b" * 64,
            4,
            fixture_pages(),
        )

        statement = ChaseStatementParser().parse(source).statement

        self.assertNotIn("SAFE-ORDER-ONE", repr(statement))
        self.assertTrue(
            all(dict(item.source_metadata)["evidence_ref"] for item in statement.transactions)
        )

    def test_ids_are_deterministic(self) -> None:
        source = ValidatedPdfDocument(
            Path("synthetic.pdf"),
            "synthetic.pdf",
            "c" * 64,
            4,
            fixture_pages(),
        )
        parser = ChaseStatementParser()

        first = parser.parse(source).statement
        second = parser.parse(source).statement

        self.assertEqual(first.statement_id, second.statement_id)
        self.assertEqual(
            tuple(item.transaction_id for item in first.transactions),
            tuple(item.transaction_id for item in second.transactions),
        )

    def test_partial_activity_row_warns_and_unknown_layout_fails(self) -> None:
        pages = list(fixture_pages())
        pages[2] = pages[2].replace(
            "12/02 AMAZON MKTPL SYNTHETIC ORDER WA 27.97",
            "12/02 INCOMPLETE ACTIVITY ROW",
        )
        partial = ValidatedPdfDocument(
            Path("partial.pdf"),
            "partial.pdf",
            "d" * 64,
            4,
            tuple(pages),
        )

        result = ChaseStatementParser().parse(partial)

        self.assertIn("chase-partial-transaction-row", {item.code for item in result.warnings})
        unsupported = ValidatedPdfDocument(
            Path("unknown.pdf"),
            "unknown.pdf",
            "e" * 64,
            1,
            ("CHASE\nACCOUNT SUMMARY\nACCOUNT ACTIVITY",),
        )
        with self.assertRaisesRegex(
            FamilySpendError,
            "Unsupported Chase credit-card layout.*masked account",
        ):
            ChaseStatementParser().parse(unsupported)


if __name__ == "__main__":
    unittest.main()
