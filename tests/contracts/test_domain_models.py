from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from family_spend.domain.models import (
    AccountConfig,
    CategoryConfig,
    Institution,
    MatchType,
    MemberConfig,
    MerchantRule,
    Money,
    NormalizedStatement,
    NormalizedTransaction,
    TransactionType,
    WorkbookConfig,
)


class MoneyContractTests(unittest.TestCase):
    def test_money_rejects_non_finite_values(self) -> None:
        for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                Money(value)

    def test_money_addition_is_exact(self) -> None:
        total = Money(Decimal("0.10")) + Money(Decimal("0.20"))

        self.assertEqual(Money(Decimal("0.30")), total)


class NormalizedTransactionContractTests(unittest.TestCase):
    def test_transaction_rejects_a_full_account_number(self) -> None:
        with self.assertRaisesRegex(ValueError, "masked"):
            NormalizedTransaction(
                transaction_id="txn-1",
                institution=Institution.AMEX,
                account_id="1234567890123456",
                member_id="member-1",
                transaction_date=date(2026, 5, 1),
                posting_date=None,
                raw_description="Example merchant",
                normalized_merchant="EXAMPLE MERCHANT",
                merchant_location=None,
                amount=Money(Decimal("12.34")),
                transaction_type=TransactionType.PURCHASE,
                category_id="dining",
                included_in_spend=True,
                reviewed=False,
            )

    def test_payment_rejects_a_positive_amount(self) -> None:
        with self.assertRaisesRegex(ValueError, "negative"):
            NormalizedTransaction(
                transaction_id="txn-1",
                institution=Institution.AMEX,
                account_id="ending-12345",
                member_id="member-1",
                transaction_date=date(2026, 5, 1),
                posting_date=None,
                raw_description="Payment received",
                normalized_merchant="PAYMENT",
                merchant_location=None,
                amount=Money(Decimal("81.02")),
                transaction_type=TransactionType.PAYMENT,
                category_id=None,
                included_in_spend=False,
                reviewed=False,
            )


class NormalizedStatementContractTests(unittest.TestCase):
    def test_statement_rejects_an_end_date_before_its_start_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "date range"):
            NormalizedStatement(
                statement_id="statement-1",
                source_name="sample.pdf",
                source_hash="a" * 64,
                institution=Institution.AMEX,
                account_id="ending-12345",
                start_date=date(2026, 5, 1),
                end_date=date(2026, 4, 1),
                closing_date=date(2026, 5, 8),
                transactions=(),
                reported_totals=(),
                warnings=(),
            )


class WorkbookConfigContractTests(unittest.TestCase):
    def test_rule_rejects_a_category_missing_from_the_workbook(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown category"):
            WorkbookConfig(
                members=(
                    MemberConfig(
                        member_id="member-1",
                        display_name="Member One",
                        aliases=("MEMBER ONE",),
                        active=True,
                    ),
                ),
                accounts=(
                    AccountConfig(
                        account_id="amex-12345",
                        institution=Institution.AMEX,
                        masked_identifier="ending-12345",
                        default_member_id="member-1",
                        display_name="AMEX",
                        active=True,
                    ),
                ),
                categories=(
                    CategoryConfig(
                        category_id="dining",
                        display_name="Dining",
                        sort_order=1,
                        active=True,
                    ),
                ),
                merchant_rules=(
                    MerchantRule(
                        rule_id="rule-1",
                        match_type=MatchType.EXACT,
                        match_value="EXAMPLE MERCHANT",
                        normalized_merchant="EXAMPLE MERCHANT",
                        category_id="missing",
                        priority=1,
                        active=True,
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
