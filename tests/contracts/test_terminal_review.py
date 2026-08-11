from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from io import StringIO

from family_spend.adapters.terminal import TerminalReviewPort
from family_spend.domain.models import (
    AccountConfig,
    CategoryConfig,
    Institution,
    MemberConfig,
    Money,
    NormalizedStatement,
    NormalizedTransaction,
    ReviewState,
    ReviewStatus,
    StatementTotal,
    TransactionType,
    WorkbookConfig,
)
from family_spend.review import ReviewEngine


def review_transaction(transaction_id: str, merchant: str) -> NormalizedTransaction:
    return NormalizedTransaction(
        transaction_id=transaction_id,
        institution=Institution.AMEX,
        account_id="ending-10005",
        member_id=None,
        transaction_date=date(2026, 6, 1),
        posting_date=None,
        raw_description=merchant,
        normalized_merchant=merchant,
        merchant_location=None,
        amount=Money(Decimal("10.00")),
        transaction_type=TransactionType.PURCHASE,
        category_id=None,
        included_in_spend=True,
        reviewed=False,
        source_metadata=(("cardholder", "MEMBER ALPHA"),),
    )


def pending_review() -> tuple[ReviewEngine, ReviewState]:
    transactions = (
        review_transaction("txn-1", "FIRST CAFE"),
        review_transaction("txn-2", "SECOND CAFE"),
    )
    statement = NormalizedStatement(
        statement_id="stmt-1",
        source_name="synthetic.pdf",
        source_hash="a" * 64,
        institution=Institution.AMEX,
        account_id="ending-10005",
        start_date=date(2026, 5, 16),
        end_date=date(2026, 6, 15),
        closing_date=date(2026, 6, 15),
        transactions=transactions,
        reported_totals=(StatementTotal("new_charges", Money(Decimal("20.00"))),),
        warnings=(),
    )
    config = WorkbookConfig(
        members=(MemberConfig("member-alpha", "Alpha", ("MEMBER ALPHA",), True),),
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
        categories=(
            CategoryConfig("uncategorized", "Uncategorized", 1, True),
            CategoryConfig("dining", "Dining", 2, True),
        ),
        merchant_rules=(),
    )
    engine = ReviewEngine()
    return engine, engine.prepare(statement, config)


class TerminalReviewPortTests(unittest.TestCase):
    def test_exception_filter_bulk_category_rule_save_and_approval(self) -> None:
        engine, state = pending_review()
        output = StringIO()
        reviewer = TerminalReviewPort(
            input_stream=StringIO(
                "filter exceptions\nbulk-category dining 1 2\nsave-rule 1 exact\napprove\n"
            ),
            output_stream=output,
            engine=engine,
        )

        decision = reviewer.review(state)

        self.assertEqual(ReviewStatus.APPROVED, decision.status)
        self.assertEqual(
            ("dining", "dining"),
            tuple(row.current.category_id for row in decision.rows),
        )
        self.assertEqual(1, len(decision.saved_rules))
        self.assertIn("Flags", output.getvalue())
        self.assertIn("CATEGORY", output.getvalue())
        self.assertIn("No rows match the current filter", output.getvalue())

    def test_unclean_approval_is_rejected_and_cancel_remains_available(self) -> None:
        engine, state = pending_review()
        output = StringIO()
        reviewer = TerminalReviewPort(
            input_stream=StringIO("approve\ncancel\n"),
            output_stream=output,
            engine=engine,
        )

        decision = reviewer.review(state)

        self.assertEqual(ReviewStatus.CANCELLED, decision.status)
        self.assertIn("approved review must be clean", output.getvalue())

    def test_unknown_category_is_rejected_against_workbook_choices(self) -> None:
        engine, state = pending_review()
        output = StringIO()
        reviewer = TerminalReviewPort(
            input_stream=StringIO("bulk-category missing 1 2\ncancel\n"),
            output_stream=output,
            engine=engine,
        )

        decision = reviewer.review(state)

        self.assertEqual(ReviewStatus.CANCELLED, decision.status)
        self.assertIn("active workbook category ID", output.getvalue())

    def test_discrepancy_can_be_approved_only_after_reasoned_override(self) -> None:
        engine, state = pending_review()
        output = StringIO()
        reviewer = TerminalReviewPort(
            input_stream=StringIO(
                "bulk-category dining 1 2\n"
                "edit 1 amount 12.00\n"
                "override Confirmed against statement\n"
                "approve\n"
            ),
            output_stream=output,
            engine=engine,
        )

        decision = reviewer.review(state)

        self.assertEqual(ReviewStatus.APPROVED, decision.status)
        self.assertEqual("overridden", decision.reconciliation.status.value)
        self.assertEqual(
            "Confirmed against statement",
            decision.reconciliation.override_reason,
        )
