from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from family_spend.domain.models import (
    AccountConfig,
    CategorizationSource,
    CategoryConfig,
    DuplicateState,
    Institution,
    MatchType,
    MemberConfig,
    MerchantRule,
    Money,
    NormalizedStatement,
    NormalizedTransaction,
    ReconciliationStatus,
    ReviewStatus,
    StatementTotal,
    TransactionType,
    WorkbookConfig,
)
from family_spend.review import (
    ReviewEngine,
    edit_review_row,
    enrich_transaction,
    included_in_spend,
    normalize_merchant,
    reconcile_statement,
    resolve_near_duplicate,
    save_rule_for_row,
)


def transaction(
    *,
    transaction_id: str = "txn-1",
    merchant: str = "CORNER CAFE",
    amount: str = "10.00",
    transaction_type: TransactionType = TransactionType.PURCHASE,
    cardholder: str | None = "CARD ALPHA",
) -> NormalizedTransaction:
    metadata = (("cardholder", cardholder),) if cardholder else ()
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
        amount=Money(Decimal(amount)),
        transaction_type=transaction_type,
        category_id=None,
        included_in_spend=True,
        reviewed=False,
        source_metadata=metadata,
    )


def statement(
    transactions: tuple[NormalizedTransaction, ...],
    *,
    reported: str | None = "10.00",
) -> NormalizedStatement:
    totals = (
        (StatementTotal("new_charges", Money(Decimal(reported))),)
        if reported is not None
        else ()
    )
    return NormalizedStatement(
        statement_id="stmt-1",
        source_name="synthetic.pdf",
        source_hash="a" * 64,
        institution=Institution.AMEX,
        account_id="ending-10005",
        start_date=date(2026, 5, 16),
        end_date=date(2026, 6, 15),
        closing_date=date(2026, 6, 15),
        transactions=transactions,
        reported_totals=totals,
        warnings=(),
    )


def rule(
    rule_id: str,
    match_type: MatchType,
    match_value: str,
    category_id: str,
    priority: int,
) -> MerchantRule:
    return MerchantRule(
        rule_id=rule_id,
        match_type=match_type,
        match_value=match_value,
        normalized_merchant=match_value,
        category_id=category_id,
        priority=priority,
        active=True,
    )


def configuration(*rules: MerchantRule) -> WorkbookConfig:
    return WorkbookConfig(
        members=(
            MemberConfig("member-alpha", "Alpha", ("CARD ALPHA",), True),
            MemberConfig("member-beta", "Beta", ("CARD BETA",), True),
        ),
        accounts=(
            AccountConfig(
                "amex-primary",
                Institution.AMEX,
                "ending-10005",
                "member-beta",
                "AMEX Primary",
                True,
            ),
        ),
        categories=(
            CategoryConfig("uncategorized", "Uncategorized", 1, True),
            CategoryConfig("dining", "Dining", 2, True),
            CategoryConfig("shopping", "Shopping", 3, True),
        ),
        merchant_rules=tuple(rules),
    )


class OwnershipAndCategorizationTests(unittest.TestCase):
    def test_alias_precedes_configured_account_owner(self) -> None:
        row = enrich_transaction(transaction(), configuration())

        self.assertEqual("member-alpha", row.current.member_id)

    def test_account_owner_is_used_when_no_alias_is_available(self) -> None:
        row = enrich_transaction(transaction(cardholder=None), configuration())

        self.assertEqual("member-beta", row.current.member_id)

    def test_ambiguous_alias_requires_review_instead_of_guessing(self) -> None:
        config = configuration()
        config = replace(
            config,
            members=(
                *config.members,
                MemberConfig("member-third", "Third", ("CARD ALPHA",), True),
            ),
        )

        row = enrich_transaction(transaction(), config)

        self.assertIsNone(row.current.member_id)
        self.assertIn("ownership-ambiguous-alias", {item.code for item in row.warnings})

    def test_inactive_account_default_requires_review(self) -> None:
        config = configuration()
        config = replace(
            config,
            members=tuple(
                replace(member, active=False)
                if member.member_id == "member-beta"
                else member
                for member in config.members
            ),
        )

        row = enrich_transaction(transaction(cardholder=None), config)

        self.assertIsNone(row.current.member_id)
        self.assertIn(
            "ownership-inactive-account-default",
            {item.code for item in row.warnings},
        )

    def test_merchant_normalization_is_separate_and_deterministic(self) -> None:
        self.assertEqual("CORNER CAFE", normalize_merchant("  SQ * Corner Café #1234 "))

    def test_exact_rule_wins_before_higher_priority_contains_rule(self) -> None:
        config = configuration(
            rule("contains", MatchType.CONTAINS, "CAFE", "shopping", 999),
            rule("exact", MatchType.EXACT, "CORNER CAFE", "dining", 1),
        )

        row = enrich_transaction(transaction(), config)

        self.assertEqual("dining", row.current.category_id)
        self.assertEqual(CategorizationSource.EXACT_RULE, row.categorization_source)

    def test_higher_priority_broader_rule_wins_deterministically(self) -> None:
        config = configuration(
            rule("low", MatchType.CONTAINS, "CAFE", "shopping", 1),
            rule("high", MatchType.CONTAINS, "CORNER", "dining", 10),
        )

        row = enrich_transaction(transaction(), config)

        self.assertEqual("dining", row.current.category_id)
        self.assertEqual(CategorizationSource.CONTAINS_RULE, row.categorization_source)

    def test_rule_for_an_inactive_category_remains_uncategorized(self) -> None:
        config = configuration(
            rule("exact", MatchType.EXACT, "CORNER CAFE", "dining", 1)
        )
        config = replace(
            config,
            categories=tuple(
                replace(category, active=False)
                if category.category_id == "dining"
                else category
                for category in config.categories
            ),
        )

        row = enrich_transaction(transaction(), config)

        self.assertEqual("uncategorized", row.current.category_id)
        self.assertEqual(CategorizationSource.UNCATEGORIZED, row.categorization_source)

    def test_spend_inclusion_depends_only_on_transaction_type(self) -> None:
        self.assertTrue(included_in_spend(TransactionType.MERCHANT_CREDIT))
        self.assertFalse(included_in_spend(TransactionType.PAYMENT))
        payment = transaction(
            amount="-10.00",
            transaction_type=TransactionType.PAYMENT,
        )

        row = enrich_transaction(payment, configuration())

        self.assertFalse(row.current.included_in_spend)
        self.assertIsNone(row.current.category_id)
        self.assertEqual(CategorizationSource.NOT_APPLICABLE, row.categorization_source)


class ReconciliationAndCleanStatusTests(unittest.TestCase):
    def test_one_cent_difference_is_within_tolerance(self) -> None:
        result = reconcile_statement(statement((transaction(),), reported="10.01"))

        self.assertEqual(ReconciliationStatus.MATCHED, result.status)
        self.assertEqual(Decimal("-0.01"), result.lines[0].difference.amount)

    def test_difference_above_one_cent_is_a_discrepancy(self) -> None:
        result = reconcile_statement(statement((transaction(),), reported="10.02"))

        self.assertEqual(ReconciliationStatus.DISCREPANCY, result.status)

    def test_cardholder_section_totals_reconcile_independently(self) -> None:
        alpha = transaction(transaction_id="txn-alpha", amount="10.00")
        beta = transaction(
            transaction_id="txn-beta",
            amount="20.00",
            cardholder="CARD BETA",
        )
        source = statement((alpha, beta), reported=None)
        source = replace(
            source,
            reported_totals=(
                StatementTotal("new_charges_for_card_alpha", Money(Decimal("10.00"))),
                StatementTotal("new_charges_for_card_beta", Money(Decimal("20.00"))),
            ),
        )

        result = reconcile_statement(source)

        self.assertEqual(ReconciliationStatus.MATCHED, result.status)
        self.assertEqual(
            (Decimal("10.00"), Decimal("20.00")),
            tuple(line.extracted.amount for line in result.lines),
        )

    def test_clean_status_is_computed_from_all_unresolved_state(self) -> None:
        config = configuration(
            rule("exact", MatchType.EXACT, "CORNER CAFE", "dining", 1)
        )
        engine = ReviewEngine()

        clean = engine.prepare(statement((transaction(),)), config)
        uncategorized = engine.prepare(statement((transaction(),)), configuration())
        near_duplicate = engine.prepare(
            statement((transaction(),)),
            config,
            duplicates={"txn-1": DuplicateState.NEAR},
        )
        unreconciled = engine.prepare(
            statement((transaction(),), reported=None),
            config,
        )

        self.assertTrue(clean.is_clean)
        self.assertFalse(uncategorized.is_clean)
        self.assertFalse(near_duplicate.is_clean)
        self.assertFalse(unreconciled.is_clean)

    def test_near_duplicate_requires_explicit_resolution(self) -> None:
        config = configuration(
            rule("exact", MatchType.EXACT, "CORNER CAFE", "dining", 1)
        )
        engine = ReviewEngine()
        state = engine.prepare(
            statement((transaction(),)),
            config,
            duplicates={"txn-1": DuplicateState.NEAR},
        )

        row = resolve_near_duplicate(state.rows[0])
        corrected = engine.decide(state, status=ReviewStatus.PENDING, rows=(row,))

        self.assertTrue(corrected.is_clean)

    def test_discrepancy_override_requires_and_retains_a_reason(self) -> None:
        config = configuration(
            rule("exact", MatchType.EXACT, "CORNER CAFE", "dining", 1)
        )
        engine = ReviewEngine()
        state = engine.prepare(statement((transaction(),), reported="11.00"), config)

        with self.assertRaisesRegex(ValueError, "non-empty"):
            engine.decide(
                state,
                status=ReviewStatus.APPROVED,
                override_reason=" ",
            )
        approved = engine.decide(
            state,
            status=ReviewStatus.APPROVED,
            override_reason="Statement total reviewed manually",
        )

        self.assertEqual(ReconciliationStatus.OVERRIDDEN, approved.reconciliation.status)
        self.assertEqual(
            "Statement total reviewed manually",
            approved.reconciliation.override_reason,
        )

    def test_matched_reconciliation_cannot_be_overridden(self) -> None:
        config = configuration(
            rule("exact", MatchType.EXACT, "CORNER CAFE", "dining", 1)
        )
        engine = ReviewEngine()
        state = engine.prepare(statement((transaction(),)), config)

        with self.assertRaisesRegex(ValueError, "only a reconciliation discrepancy"):
            engine.decide(
                state,
                status=ReviewStatus.APPROVED,
                override_reason="Unnecessary override",
            )


class ReviewCorrectionTests(unittest.TestCase):
    def test_type_edit_recomputes_sign_and_spend_inclusion(self) -> None:
        engine = ReviewEngine()
        state = engine.prepare(statement((transaction(),)), configuration())

        corrected = edit_review_row(state.rows[0], "type", "payment")

        self.assertEqual(TransactionType.PAYMENT, corrected.current.transaction_type)
        self.assertEqual(Decimal("-10.00"), corrected.current.amount.amount)
        self.assertFalse(corrected.current.included_in_spend)
        self.assertIsNone(corrected.current.category_id)

    def test_unknown_member_or_category_ids_cannot_produce_clean_state(self) -> None:
        engine = ReviewEngine()
        config = configuration(
            rule("exact", MatchType.EXACT, "CORNER CAFE", "dining", 1)
        )
        state = engine.prepare(statement((transaction(),)), config)
        unknown_member = edit_review_row(state.rows[0], "member", "missing-member")
        unknown_category = edit_review_row(unknown_member, "category", "missing-category")

        updated = engine.decide(
            state,
            status=ReviewStatus.PENDING,
            rows=(unknown_category,),
        )

        self.assertFalse(updated.is_clean)

    def test_explicit_edits_update_only_the_selected_row(self) -> None:
        engine = ReviewEngine()
        first = transaction(transaction_id="txn-1")
        second = transaction(transaction_id="txn-2", merchant="SECOND MERCHANT")
        state = engine.prepare(
            statement((first, second), reported="20.00"),
            configuration(),
        )
        corrected = edit_review_row(state.rows[0], "member", "member-alpha")
        corrected = edit_review_row(corrected, "merchant", "Corrected Café")
        corrected = edit_review_row(corrected, "date", "2026-06-02")
        corrected = edit_review_row(corrected, "amount", "12.50")
        corrected = edit_review_row(corrected, "category", "dining")

        updated = engine.decide(
            state,
            status=ReviewStatus.PENDING,
            rows=(corrected, state.rows[1]),
        )

        self.assertEqual("CORRECTED CAFE", updated.rows[0].current.normalized_merchant)
        self.assertEqual(date(2026, 6, 2), updated.rows[0].current.transaction_date)
        self.assertEqual(Decimal("12.50"), updated.rows[0].current.amount.amount)
        self.assertEqual("dining", updated.rows[0].current.category_id)
        self.assertEqual("SECOND MERCHANT", updated.rows[1].current.normalized_merchant)

    def test_saved_rule_categorizes_the_next_simulated_statement(self) -> None:
        engine = ReviewEngine()
        state = engine.prepare(statement((transaction(),)), configuration())
        corrected = edit_review_row(state.rows[0], "category", "dining")
        saved_rule = save_rule_for_row(corrected, MatchType.EXACT)
        next_config = configuration(saved_rule)

        next_row = enrich_transaction(transaction(transaction_id="txn-next"), next_config)

        self.assertEqual("dining", next_row.current.category_id)
        self.assertEqual(CategorizationSource.EXACT_RULE, next_row.categorization_source)
