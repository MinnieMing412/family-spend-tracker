from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from family_spend.domain.models import DetectionStatus, Institution
from family_spend.errors import FamilySpendError
from family_spend.ingestion import (
    MarkerParserRegistry,
    ParserRegistration,
    PdfValidator,
    ValidatedPdfDocument,
    discover_pdfs,
)
from family_spend.parsers import AmexStatementParser
from tests.pdf_factory import encrypt_pdf, write_text_pdf

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "amex"


def fixture_pages() -> tuple[str, ...]:
    return tuple((FIXTURE_ROOT / "synthetic_statement.txt").read_text().split("\f"))


def amex_registry() -> MarkerParserRegistry:
    return MarkerParserRegistry(
        (
            ParserRegistration(
                Institution.AMEX,
                ("American Express", "Account Ending", "Payments and Credits"),
                AmexStatementParser(),
            ),
        )
    )


class PdfDiscoveryTests(unittest.TestCase):
    def test_discovers_pdfs_recursively_in_stable_relative_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "later").mkdir()
            (root / "A.pdf").write_bytes(b"fixture")
            (root / "later" / "b.PDF").write_bytes(b"fixture")
            (root / "ignore.txt").write_text("not a statement")

            discovered = discover_pdfs(root)

            self.assertEqual((root / "A.pdf", root / "later" / "b.PDF"), discovered)

    def test_empty_directory_is_an_explicit_failure(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(FamilySpendError, "No PDF statements"),
        ):
            discover_pdfs(Path(directory))


class PdfValidationTests(unittest.TestCase):
    def test_extracts_text_page_count_and_exact_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statement.pdf"
            write_text_pdf(path, fixture_pages())

            validated = PdfValidator().validate(path)

            self.assertEqual(2, validated.page_count)
            self.assertIn("AMERICAN EXPRESS", validated.page_texts[0])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), validated.sha256)

    def test_rejects_an_image_only_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scanned.pdf"
            write_text_pdf(path, ("",))

            with self.assertRaisesRegex(FamilySpendError, "no extractable text"):
                PdfValidator().validate(path)

    def test_rejects_an_encrypted_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            encrypted = root / "encrypted.pdf"
            write_text_pdf(source, ("Synthetic statement",))
            encrypt_pdf(source, encrypted)

            with self.assertRaisesRegex(FamilySpendError, "Encrypted PDF"):
                PdfValidator().validate(encrypted)

    def test_rejects_a_corrupt_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrupt.pdf"
            path.write_bytes(b"%PDF-1.4 definitely not a complete PDF")

            with self.assertRaisesRegex(FamilySpendError, "corrupt|could not be read"):
                PdfValidator().validate(path)


class InstitutionDetectionTests(unittest.TestCase):
    def test_detects_amex_from_multiple_content_markers_not_the_filename(self) -> None:
        source = ValidatedPdfDocument(
            Path("unhelpful-name.pdf"),
            "unhelpful-name.pdf",
            "a" * 64,
            1,
            ("AMERICAN EXPRESS\nAccount Ending 10005\nPayments and Credits",),
        )

        detection = amex_registry().detect(source)

        self.assertEqual(DetectionStatus.DETECTED, detection.status)
        self.assertEqual((Institution.AMEX,), detection.institutions)
        self.assertGreaterEqual(len(detection.evidence_refs), 2)

    def test_returns_unsupported_when_multiple_markers_do_not_match(self) -> None:
        source = ValidatedPdfDocument(
            Path("amex.pdf"), "amex.pdf", "a" * 64, 1, ("UNRELATED BANK",)
        )

        detection = amex_registry().detect(source)

        self.assertEqual(DetectionStatus.UNSUPPORTED, detection.status)
        with self.assertRaisesRegex(FamilySpendError, "Unsupported"):
            amex_registry().parser_for(source)

    def test_returns_ambiguous_when_two_registered_institutions_match(self) -> None:
        parser = AmexStatementParser()
        registry = MarkerParserRegistry(
            (
                ParserRegistration(
                    Institution.AMEX,
                    ("shared marker one", "shared marker two"),
                    parser,
                ),
                ParserRegistration(
                    Institution.CHASE,
                    ("shared marker one", "shared marker two"),
                    parser,
                ),
            )
        )
        source = ValidatedPdfDocument(
            Path("statement.pdf"),
            "statement.pdf",
            "a" * 64,
            1,
            ("shared marker one\nshared marker two",),
        )

        detection = registry.detect(source)

        self.assertEqual(DetectionStatus.AMBIGUOUS, detection.status)
        self.assertEqual((Institution.AMEX, Institution.CHASE), detection.institutions)
        with self.assertRaisesRegex(FamilySpendError, "ambiguous"):
            registry.parser_for(source)


class AmexParserContractTests(unittest.TestCase):
    def test_synthetic_statement_matches_expected_normalized_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.pdf"
            write_text_pdf(path, fixture_pages())
            source = PdfValidator().validate(path)
            expected = json.loads(
                (FIXTURE_ROOT / "synthetic_statement.expected.json").read_text()
            )

            result = AmexStatementParser().parse(source)

            statement = result.statement
            self.assertEqual(expected["account_id"], statement.account_id)
            self.assertEqual(expected["start_date"], statement.start_date.isoformat())
            self.assertEqual(expected["end_date"], statement.end_date.isoformat())
            self.assertEqual(expected["closing_date"], statement.closing_date.isoformat())
            self.assertEqual(expected["transaction_count"], len(statement.transactions))
            actual_transactions = [
                [
                    transaction.transaction_date.isoformat(),
                    transaction.posting_date.isoformat()
                    if transaction.posting_date
                    else None,
                    transaction.transaction_type.value,
                    str(transaction.amount.amount),
                ]
                for transaction in statement.transactions
            ]
            self.assertEqual(expected["transactions"], actual_transactions)
            actual_totals = {
                total.section: str(total.amount.amount)
                for total in statement.reported_totals
            }
            self.assertEqual(expected["reported_totals"], actual_totals)

    def test_preserves_cardholder_posting_marker_multiline_text_and_evidence(self) -> None:
        source = ValidatedPdfDocument(
            Path("synthetic.pdf"),
            "synthetic.pdf",
            "b" * 64,
            2,
            fixture_pages(),
        )

        statement = AmexStatementParser().parse(source).statement

        payment_metadata = dict(statement.transactions[0].source_metadata)
        self.assertEqual("*", payment_metadata["posting_date_marker"])
        self.assertTrue(payment_metadata["evidence_ref"].startswith("page-1:line-"))
        multiline = statement.transactions[3]
        self.assertEqual("MARKETPLACE SEATTLE WA", multiline.raw_description)
        self.assertEqual("SEATTLE WA", multiline.merchant_location)
        alpha_metadata = dict(statement.transactions[2].source_metadata)
        beta_metadata = dict(statement.transactions[5].source_metadata)
        self.assertEqual("MEMBER ALPHA", alpha_metadata["cardholder"])
        self.assertEqual("MEMBER BETA", beta_metadata["cardholder"])

    def test_ids_are_deterministic_for_the_same_pdf_bytes(self) -> None:
        source = ValidatedPdfDocument(
            Path("synthetic.pdf"),
            "synthetic.pdf",
            "c" * 64,
            2,
            fixture_pages(),
        )
        parser = AmexStatementParser()

        first = parser.parse(source).statement
        second = parser.parse(source).statement

        self.assertEqual(first.statement_id, second.statement_id)
        self.assertEqual(
            tuple(transaction.transaction_id for transaction in first.transactions),
            tuple(transaction.transaction_id for transaction in second.transactions),
        )

    def test_partial_transaction_row_emits_a_structured_warning(self) -> None:
        page = fixture_pages()[0].replace(
            "Cardmember: MEMBER BETA",
            "05/25/26 INCOMPLETE MERCHANT\nCardmember: MEMBER BETA",
        )
        source = ValidatedPdfDocument(
            Path("partial.pdf"),
            "partial.pdf",
            "d" * 64,
            2,
            (page, fixture_pages()[1]),
        )

        result = AmexStatementParser().parse(source)

        self.assertIn("amex-partial-transaction-row", {warning.code for warning in result.warnings})
        self.assertTrue(all(warning.evidence_ref for warning in result.warnings))
