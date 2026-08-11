from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from family_spend.domain.models import (
    DetectionStatus,
    Institution,
    ReconciliationStatus,
    TransactionType,
)
from family_spend.errors import FamilySpendError
from family_spend.ingestion import (
    MarkerParserRegistry,
    ParserRegistration,
    PdfValidator,
    ValidatedPdfDocument,
)
from family_spend.parsers import BankOfAmericaStatementParser
from family_spend.review import reconcile_statement
from tests.pdf_factory import write_text_pdf

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "bank_of_america"


def fixture_pages() -> tuple[str, ...]:
    return tuple(
        (FIXTURE_ROOT / "synthetic_credit_card_statement.txt").read_text().split("\f")
    )


def boa_registry() -> MarkerParserRegistry:
    return MarkerParserRegistry(
        (
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
    )


class BankOfAmericaDetectionTests(unittest.TestCase):
    def test_detects_boa_from_content_in_an_unhelpful_filename(self) -> None:
        source = ValidatedPdfDocument(
            Path("unhelpful-name.pdf"),
            "unhelpful-name.pdf",
            "a" * 64,
            1,
            (
                "BANK OF AMERICA\nAccount Summary\n"
                "Payments and Other Credits\nPurchases and Adjustments",
            ),
        )

        detection = boa_registry().detect(source)

        self.assertEqual(DetectionStatus.DETECTED, detection.status)
        self.assertEqual((Institution.BANK_OF_AMERICA,), detection.institutions)
        self.assertGreaterEqual(len(detection.evidence_refs), 2)

    def test_detected_boa_with_unknown_layout_has_actionable_diagnostic(self) -> None:
        source = ValidatedPdfDocument(
            Path("unknown.pdf"),
            "unknown.pdf",
            "b" * 64,
            1,
            (
                "BANK OF AMERICA\nAccount Summary\n"
                "Payments and Other Credits\nPurchases and Adjustments",
            ),
        )

        with self.assertRaisesRegex(
            FamilySpendError,
            "Unsupported Bank of America credit-card layout.*masked account",
        ):
            boa_registry().parser_for(source).parse(source)


class BankOfAmericaParserContractTests(unittest.TestCase):
    def test_synthetic_statement_matches_expected_normalized_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.pdf"
            write_text_pdf(path, fixture_pages())
            source = PdfValidator().validate(path)
            expected = json.loads(
                (FIXTURE_ROOT / "synthetic_credit_card_statement.expected.json").read_text()
            )

            result = BankOfAmericaStatementParser().parse(source)

        statement = result.statement
        self.assertEqual(Institution.BANK_OF_AMERICA, statement.institution)
        self.assertEqual(expected["account_id"], statement.account_id)
        self.assertEqual(expected["start_date"], statement.start_date.isoformat())
        self.assertEqual(expected["end_date"], statement.end_date.isoformat())
        self.assertEqual(expected["closing_date"], statement.closing_date.isoformat())
        self.assertEqual(expected["transaction_count"], len(statement.transactions))
        actual_transactions = [
            [
                transaction.transaction_date.isoformat(),
                transaction.posting_date.isoformat() if transaction.posting_date else None,
                transaction.transaction_type.value,
                str(transaction.amount.amount),
            ]
            for transaction in statement.transactions
        ]
        self.assertEqual(expected["transactions"], actual_transactions)
        self.assertEqual(
            expected["reported_totals"],
            {
                total.section: str(total.amount.amount)
                for total in statement.reported_totals
            },
        )
        self.assertEqual(
            ReconciliationStatus.MATCHED,
            reconcile_statement(statement).status,
        )

    def test_continuation_page_metadata_masking_and_multiline_description(self) -> None:
        source = ValidatedPdfDocument(
            Path("synthetic.pdf"),
            "synthetic.pdf",
            "c" * 64,
            2,
            fixture_pages(),
        )

        statement = BankOfAmericaStatementParser().parse(source).statement

        multiline = statement.transactions[4]
        metadata = dict(multiline.source_metadata)
        self.assertEqual("HOTEL RESERVATION", multiline.raw_description)
        self.assertEqual("MEMBER ALPHA", metadata["cardholder"])
        self.assertEqual("ending-4321", metadata["row_account"])
        self.assertEqual("012349", metadata["reference_suffix"])
        self.assertTrue(metadata["evidence_ref"].startswith("page-2:line-"))
        self.assertNotIn("123456789012349", repr(statement))

    def test_ids_are_deterministic_for_the_same_pdf_bytes(self) -> None:
        source = ValidatedPdfDocument(
            Path("synthetic.pdf"),
            "synthetic.pdf",
            "d" * 64,
            2,
            fixture_pages(),
        )
        parser = BankOfAmericaStatementParser()

        first = parser.parse(source).statement
        second = parser.parse(source).statement

        self.assertEqual(first.statement_id, second.statement_id)
        self.assertEqual(
            tuple(item.transaction_id for item in first.transactions),
            tuple(item.transaction_id for item in second.transactions),
        )

    def test_cash_advances_and_balance_transfers_use_common_transaction_types(self) -> None:
        source = ValidatedPdfDocument(
            Path("activity.pdf"),
            "activity.pdf",
            "f" * 64,
            1,
            (
                "BANK OF AMERICA\n"
                "Account Number: XXXX XXXX XXXX 4321\n"
                "Billing Cycle: 05/16/2026 to 06/15/2026\n"
                "Statement Closing Date: 06/15/2026\n"
                "Account Summary\n"
                "Purchases and Adjustments $1.00\n"
                "Transactions\n"
                "Balance Transfers\n"
                "05/20 05/20 BALANCE TRANSFER 123456789012345 4321 $250.00\n"
                "Cash Advances\n"
                "05/22 05/22 ATM CASH ADVANCE 123456789012346 4321 $80.00",
            ),
        )

        transactions = BankOfAmericaStatementParser().parse(source).statement.transactions

        self.assertEqual(
            (TransactionType.TRANSFER, TransactionType.CASH_ADVANCE),
            tuple(item.transaction_type for item in transactions),
        )
        self.assertFalse(transactions[0].included_in_spend)
        self.assertTrue(transactions[1].included_in_spend)

    def test_partial_transaction_row_emits_structured_warning(self) -> None:
        first_page = fixture_pages()[0].replace(
            "Purchases and Adjustments\n05/18",
            "Purchases and Adjustments\n05/25 05/26 INCOMPLETE MERCHANT\n05/18",
        )
        source = ValidatedPdfDocument(
            Path("partial.pdf"),
            "partial.pdf",
            "e" * 64,
            2,
            (first_page, fixture_pages()[1]),
        )

        result = BankOfAmericaStatementParser().parse(source)

        partial = tuple(
            warning
            for warning in result.warnings
            if warning.code == "boa-partial-transaction-row"
        )
        self.assertEqual(1, len(partial))
        self.assertIsNotNone(partial[0].evidence_ref)


if __name__ == "__main__":
    unittest.main()
