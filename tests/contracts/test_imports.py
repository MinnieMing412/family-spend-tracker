from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from family_spend.adapters.memory import (
    FixedClock,
    InMemoryStructuredCache,
    InMemoryWorkbookGateway,
)
from family_spend.domain.models import (
    DuplicateState,
    ImportStatus,
    Institution,
    Money,
    NormalizedTransaction,
    TransactionType,
)
from family_spend.imports import (
    SingleImportWorkflow,
    assign_fingerprints,
    classify_duplicates,
)
from family_spend.review import ReviewEngine
from tests.import_helpers import (
    ApprovingReviewer,
    build_ingestion,
    workbook_configuration,
    write_statement,
)


def transaction(
    transaction_id: str,
    *,
    merchant: str = "CORNER CAFE",
    amount: str = "10.00",
    transaction_date: date = date(2026, 6, 1),
) -> NormalizedTransaction:
    return NormalizedTransaction(
        transaction_id=transaction_id,
        institution=Institution.AMEX,
        account_id="ending-10005",
        member_id="member-alpha",
        transaction_date=transaction_date,
        posting_date=None,
        raw_description=merchant,
        normalized_merchant=merchant,
        merchant_location=None,
        amount=Money(Decimal(amount)),
        transaction_type=TransactionType.PURCHASE,
        category_id="other",
        included_in_spend=True,
        reviewed=True,
    )


class FingerprintAndDuplicateTests(unittest.TestCase):
    def test_occurrence_discriminator_is_deterministic_and_overlap_stable(self) -> None:
        repeated = (transaction("txn-1"), transaction("txn-2"))

        first = assign_fingerprints(repeated)
        second = assign_fingerprints(repeated)
        overlap = assign_fingerprints((transaction("txn-overlap"),))

        self.assertEqual(
            tuple(item.fingerprint for item in first),
            tuple(item.fingerprint for item in second),
        )
        self.assertNotEqual(first[0].fingerprint, first[1].fingerprint)
        self.assertEqual(first[0].fingerprint, overlap[0].fingerprint)

    def test_exact_match_wins_and_similar_candidate_is_near(self) -> None:
        source = assign_fingerprints((transaction("txn-source"),))[0]
        exact = assign_fingerprints((transaction("txn-existing"),))[0]
        near = transaction("txn-near", merchant="CORNER CAFE SHOP")

        exact_result = classify_duplicates((source,), (exact,), (near,))
        near_result = classify_duplicates((source,), (), (near,))

        self.assertEqual(DuplicateState.EXACT, exact_result["txn-source"])
        self.assertEqual(DuplicateState.NEAR, near_result["txn-source"])

    def test_different_amount_or_distant_date_is_not_near(self) -> None:
        source = assign_fingerprints((transaction("txn-source"),))[0]
        candidates = (
            transaction("txn-amount", merchant="CORNER CAFE SHOP", amount="11.00"),
            transaction(
                "txn-date",
                merchant="CORNER CAFE SHOP",
                transaction_date=date(2026, 6, 8),
            ),
        )

        result = classify_duplicates((source,), (), candidates)

        self.assertEqual(DuplicateState.NONE, result["txn-source"])


class SingleImportWorkflowTests(unittest.TestCase):
    def _workflow(
        self,
        gateway: InMemoryWorkbookGateway,
        engine: ReviewEngine,
        reviewer: ApprovingReviewer,
        cache: InMemoryStructuredCache | None = None,
    ) -> SingleImportWorkflow:
        return SingleImportWorkflow(
            ingestion=build_ingestion(),
            review_engine=engine,
            reviewer=reviewer,
            workbook=gateway,
            configuration=gateway.load_configuration(),
            cache=cache or InMemoryStructuredCache(),
            clock=FixedClock(datetime(2026, 8, 10, 12, 0, tzinfo=UTC)),
        )

    def test_same_statement_is_skipped_without_a_second_review(self) -> None:
        engine = ReviewEngine()
        reviewer = ApprovingReviewer(engine)
        gateway = InMemoryWorkbookGateway(workbook_configuration())
        workflow = self._workflow(gateway, engine, reviewer)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statement.pdf"
            write_statement(path)

            first = workflow.execute(path)
            second = workflow.execute(path)

        self.assertEqual(ImportStatus.COMPLETE, first.status)
        self.assertEqual(ImportStatus.SKIPPED, second.status)
        self.assertEqual(1, reviewer.call_count)
        self.assertEqual(8, len(gateway.transactions_in_window("ending-10005", date.min, date.max)))

    def test_overlapping_statement_skips_exact_rows(self) -> None:
        engine = ReviewEngine()
        reviewer = ApprovingReviewer(engine)
        gateway = InMemoryWorkbookGateway(workbook_configuration())
        workflow = self._workflow(gateway, engine, reviewer)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_path = root / "first.pdf"
            overlap_path = root / "overlap.pdf"
            write_statement(first_path)
            write_statement(
                overlap_path,
                replace_text=("Synthetic Card Statement", "Synthetic Card Statement Copy"),
            )

            workflow.execute(first_path)
            overlap = workflow.execute(overlap_path)

        self.assertEqual(8, overlap.exact_duplicate_count)
        self.assertEqual(0, overlap.imported_count)
        self.assertEqual(8, len(gateway.transactions_in_window("ending-10005", date.min, date.max)))

    def test_near_duplicate_is_presented_and_explicitly_preserved(self) -> None:
        engine = ReviewEngine()
        reviewer = ApprovingReviewer(engine)
        gateway = InMemoryWorkbookGateway(workbook_configuration())
        workflow = self._workflow(gateway, engine, reviewer)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_path = root / "first.pdf"
            near_path = root / "near.pdf"
            write_statement(first_path)
            write_statement(
                near_path,
                replace_text=("COFFEE SHOP $12.34", "COFFEE SHOPPE $12.34"),
            )

            workflow.execute(first_path)
            outcome = workflow.execute(near_path)

        self.assertIn(DuplicateState.NEAR, reviewer.seen_duplicate_states[1])
        self.assertEqual(7, outcome.exact_duplicate_count)
        self.assertEqual(1, outcome.imported_count)
        self.assertEqual(9, len(gateway.transactions_in_window("ending-10005", date.min, date.max)))

    def test_retry_converges_after_each_injected_write_failure(self) -> None:
        for stage in ("before_write", "after_transactions", "before_finalize"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                engine = ReviewEngine()
                reviewer = ApprovingReviewer(engine, save_rule=True)
                gateway = InMemoryWorkbookGateway(workbook_configuration())
                workflow = self._workflow(gateway, engine, reviewer)
                path = Path(directory) / "statement.pdf"
                write_statement(path)
                gateway.fail_next_commit_at(stage)

                with self.assertRaisesRegex(RuntimeError, stage):
                    workflow.execute(path)
                result = workflow.execute(path)

                self.assertEqual(ImportStatus.COMPLETE, result.status)
                self.assertEqual(
                    8,
                    len(gateway.transactions_in_window("ending-10005", date.min, date.max)),
                )
                self.assertEqual(1, len(gateway.load_configuration().merchant_rules))
