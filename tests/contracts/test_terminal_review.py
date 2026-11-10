from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from io import StringIO

from family_spend.adapters.terminal import TerminalReviewPort
from family_spend.domain.models import (
    AccountConfig,
    CategoryConfig,
    DomainWarning,
    Institution,
    MatchType,
    MemberConfig,
    MerchantRule,
    Money,
    NormalizedStatement,
    NormalizedTransaction,
    ReviewState,
    ReviewStatus,
    StatementTotal,
    TransactionType,
    WarningSeverity,
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
        review_transaction("txn-3", "FIRST CAFE"),
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
        reported_totals=(StatementTotal("new_charges", Money(Decimal("30.00"))),),
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
                "filter exceptions\nbulk-category dining 1 2 3\nsave-rules exact 1\n"
                "filter all\napprove\n"
            ),
            output_stream=output,
            engine=engine,
        )

        decision = reviewer.review(state)

        self.assertEqual(ReviewStatus.APPROVED, decision.status)
        self.assertEqual(
            ("dining", "dining", "dining"),
            tuple(row.current.category_id for row in decision.rows),
        )
        self.assertEqual(1, len(decision.saved_rules))
        self.assertIn("Flags", output.getvalue())
        self.assertIn("Rule Saved", output.getvalue())
        final_table = output.getvalue().split("Reconciliation:")[-2]
        final_rows = [line for line in final_table.splitlines() if "| 2026-" in line]
        self.assertEqual(2, sum("| YES        |" in row for row in final_rows))
        self.assertEqual(1, sum("| NO         |" in row for row in final_rows))
        self.assertIn("CATEGORY", output.getvalue())
        self.assertIn("No rows match the current filter", output.getvalue())

    def test_save_rules_saves_distinct_selected_merchants_once(self) -> None:
        engine, state = pending_review()
        output = StringIO()
        reviewer = TerminalReviewPort(
            input_stream=StringIO(
                "bulk-category dining 1 2 3\n"
                "save-rules exact 1 2 3\n"
                "approve\n"
            ),
            output_stream=output,
            engine=engine,
        )

        decision = reviewer.review(state)

        self.assertEqual(ReviewStatus.APPROVED, decision.status)
        self.assertEqual(2, len(decision.saved_rules))
        self.assertEqual(
            {"FIRST CAFE", "SECOND CAFE"},
            {rule.match_value for rule in decision.saved_rules},
        )
        final_table = output.getvalue().split("Reconciliation:")[-2]
        final_rows = [line for line in final_table.splitlines() if "| 2026-" in line]
        self.assertTrue(all("| YES        |" in row for row in final_rows))

    def test_save_rules_unsaved_saves_every_eligible_uncovered_merchant(self) -> None:
        engine, state = pending_review()
        output = StringIO()
        reviewer = TerminalReviewPort(
            input_stream=StringIO(
                "bulk-category dining 1 2 3\n"
                "save-rules exact 1\n"
                "save-rules exact unsaved\n"
                "approve\n"
            ),
            output_stream=output,
            engine=engine,
        )

        decision = reviewer.review(state)

        self.assertEqual(ReviewStatus.APPROVED, decision.status)
        self.assertEqual(2, len(decision.saved_rules))
        self.assertEqual(
            {"FIRST CAFE", "SECOND CAFE"},
            {rule.match_value for rule in decision.saved_rules},
        )
        final_table = output.getvalue().split("Reconciliation:")[-2]
        final_rows = [line for line in final_table.splitlines() if "| 2026-" in line]
        self.assertTrue(all("| YES        |" in row for row in final_rows))

    def test_unsaved_filter_shows_only_eligible_rows_without_rule_coverage(self) -> None:
        engine, state = pending_review()
        output = StringIO()
        reviewer = TerminalReviewPort(
            input_stream=StringIO(
                "bulk-category dining 1 2 3\n"
                "save-rules exact 1\n"
                "filter unsaved\n"
                "cancel\n"
            ),
            output_stream=output,
            engine=engine,
        )

        reviewer.review(state)

        final_table = output.getvalue().split("Reconciliation:")[-2]
        final_rows = [line for line in final_table.splitlines() if "| 2026-" in line]
        self.assertEqual(1, len(final_rows))
        self.assertIn("SECOND CAFE", final_rows[0])
        self.assertIn("| NO         |", final_rows[0])

    def test_existing_workbook_rule_is_shown_as_saved(self) -> None:
        engine, state = pending_review()
        rule = MerchantRule(
            rule_id="rule-first-cafe",
            match_type=MatchType.EXACT,
            match_value="FIRST CAFE",
            normalized_merchant="FIRST CAFE",
            category_id="dining",
            priority=100,
            active=True,
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
            merchant_rules=(rule,),
        )
        state = engine.prepare(state.statement, config)
        output = StringIO()

        TerminalReviewPort(
            input_stream=StringIO("cancel\n"),
            output_stream=output,
            engine=engine,
        ).review(state)

        rows = [line for line in output.getvalue().splitlines() if "FIRST CAFE" in line]
        self.assertEqual(2, len(rows))
        self.assertTrue(all("| YES        |" in row for row in rows))

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
        self.assertIn("approval blocked; resolve row(s) 1, 2, 3", output.getvalue())

    def test_statement_warning_is_visible_and_requires_explicit_acknowledgement(self) -> None:
        engine, state = pending_review()
        warning = DomainWarning(
            code="parser-partial-row",
            message="One statement row could not be parsed.",
            severity=WarningSeverity.WARNING,
            evidence_ref="page-2:line-17",
        )
        state = replace(
            state,
            statement=replace(state.statement, warnings=(warning,)),
            source_path="/private/statements/chase-warning.pdf",
        )
        output = StringIO()
        reviewer = TerminalReviewPort(
            input_stream=StringIO(
                "bulk-category dining 1 2 3\n"
                "approve\n"
                "acknowledge-warning parser-partial-row\n"
                "approve\n"
            ),
            output_stream=output,
            engine=engine,
        )

        decision = reviewer.review(state)

        self.assertEqual(ReviewStatus.APPROVED, decision.status)
        self.assertEqual(("parser-partial-row",), decision.acknowledged_warning_codes)
        rendered = output.getvalue()
        self.assertIn(
            "approval blocked; acknowledge statement warning(s) parser-partial-row "
            "in /private/statements/chase-warning.pdf",
            rendered,
        )
        self.assertIn(
            "Statement warnings for /private/statements/chase-warning.pdf:",
            rendered,
        )
        self.assertIn("parser-partial-row [BLOCKING]", rendered)
        self.assertIn("parser-partial-row [ACKNOWLEDGED]", rendered)
        self.assertIn("page-2:line-17", rendered)

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
                "bulk-category dining 3\n"
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

    def test_bulk_merchant_renames_only_selected_rows(self) -> None:
        engine, state = pending_review()
        output = StringIO()
        reviewer = TerminalReviewPort(
            input_stream=StringIO("bulk-merchant LUCKY MARKET 1 2\ncancel\n"),
            output_stream=output,
            engine=engine,
        )

        decision = reviewer.review(state)

        self.assertEqual(ReviewStatus.CANCELLED, decision.status)
        self.assertEqual(
            ("LUCKY MARKET", "LUCKY MARKET", "FIRST CAFE"),
            tuple(row.current.normalized_merchant for row in decision.rows),
        )
        rendered = output.getvalue()
        self.assertGreater(rendered.rfind("Commands:"), rendered.rfind("Reconciliation:"))
        self.assertIn("bulk-merchant MERCHANT ROW [ROW ...]", rendered)

    def test_bulk_merchant_requires_rows_and_merchant(self) -> None:
        engine, state = pending_review()
        output = StringIO()

        decision = TerminalReviewPort(
            input_stream=StringIO("bulk-merchant LUCKY MARKET\ncancel\n"),
            output_stream=output,
            engine=engine,
        ).review(state)

        self.assertEqual(ReviewStatus.CANCELLED, decision.status)
        self.assertIn("MERCHANT followed by ROW [ROW ...]", output.getvalue())

    def test_bulk_merchant_updates_every_exact_reference_merchant_match(self) -> None:
        engine, state = pending_review()

        decision = TerminalReviewPort(
            input_stream=StringIO("bulk-merchant LUCKY --same-as 1\ncancel\n"),
            output_stream=StringIO(),
            engine=engine,
        ).review(state)

        self.assertEqual(
            ("LUCKY", "SECOND CAFE", "LUCKY"),
            tuple(row.current.normalized_merchant for row in decision.rows),
        )

    def test_bulk_category_updates_every_exact_reference_merchant_match(self) -> None:
        engine, state = pending_review()

        decision = TerminalReviewPort(
            input_stream=StringIO("bulk-category dining --same-as 1\ncancel\n"),
            output_stream=StringIO(),
            engine=engine,
        ).review(state)

        self.assertEqual(
            ("dining", "uncategorized", "dining"),
            tuple(row.current.category_id for row in decision.rows),
        )
