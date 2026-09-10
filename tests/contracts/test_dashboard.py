from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from family_spend.dashboard import (
    DashboardFilters,
    build_dashboard_layout,
    calculate_dashboard,
)
from family_spend.domain.models import (
    Institution,
    Money,
    NormalizedTransaction,
    TransactionType,
)


def transaction(
    transaction_id: str,
    amount: str,
    transaction_type: TransactionType,
    category: str | None,
    transaction_date: date,
    *,
    member: str = "member-a",
    merchant: str = "MERCHANT",
    reviewed: bool = True,
    fingerprint: str | None = None,
) -> NormalizedTransaction:
    return NormalizedTransaction(
        transaction_id=transaction_id,
        fingerprint=fingerprint or f"fingerprint-{transaction_id}",
        statement_id="import-1",
        institution=Institution.AMEX,
        account_id="ending-12345",
        member_id=member,
        transaction_date=transaction_date,
        posting_date=None,
        raw_description=merchant,
        normalized_merchant=merchant,
        merchant_location=None,
        amount=Money(Decimal(amount)),
        transaction_type=transaction_type,
        category_id=category,
        included_in_spend=False,
        reviewed=reviewed,
    )


class DashboardAnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.filters = DashboardFilters(date(2026, 1, 1), date(2026, 3, 31))
        self.transactions = (
            transaction(
                "purchase",
                "100",
                TransactionType.PURCHASE,
                "groceries",
                date(2026, 1, 5),
                merchant="MARKET",
            ),
            transaction(
                "refund",
                "-150",
                TransactionType.MERCHANT_CREDIT,
                "groceries",
                date(2026, 1, 10),
                merchant="MARKET",
            ),
            transaction(
                "fee",
                "10",
                TransactionType.FEE,
                "fees",
                date(2026, 2, 1),
                merchant="BANK FEE",
            ),
            transaction(
                "cash",
                "50",
                TransactionType.CASH_ADVANCE,
                "cash",
                date(2026, 3, 1),
                member="member-b",
                merchant="ATM",
            ),
            transaction(
                "uncategorized",
                "25",
                TransactionType.PURCHASE,
                "uncategorized",
                date(2026, 3, 5),
                member="member-b",
                merchant="UNKNOWN",
            ),
            transaction(
                "interest",
                "20",
                TransactionType.INTEREST,
                None,
                date(2026, 2, 2),
            ),
            transaction(
                "other",
                "40",
                TransactionType.OTHER,
                "other",
                date(2026, 2, 2),
            ),
            transaction(
                "rewards",
                "15",
                TransactionType.REWARDS,
                None,
                date(2026, 2, 2),
            ),
            transaction(
                "payment",
                "-500",
                TransactionType.PAYMENT,
                None,
                date(2026, 2, 3),
            ),
            transaction(
                "transfer",
                "70",
                TransactionType.TRANSFER,
                None,
                date(2026, 2, 3),
            ),
            transaction(
                "unapproved",
                "1000",
                TransactionType.PURCHASE,
                "shopping",
                date(2026, 2, 4),
                reviewed=False,
            ),
            transaction(
                "duplicate-row",
                "100",
                TransactionType.PURCHASE,
                "groceries",
                date(2026, 1, 5),
                fingerprint="fingerprint-purchase",
            ),
        )

    def test_spend_rules_refunds_zero_months_and_duplicates(self) -> None:
        result = calculate_dashboard(self.transactions, self.filters)

        self.assertEqual(Decimal("35"), result.total_net_spend)
        self.assertEqual(Decimal("35") / 3, result.average_monthly_spend)
        self.assertEqual("cash", result.largest_category)
        self.assertEqual(1, result.uncategorized_count)
        self.assertEqual(1, result.cash_advance_count)
        self.assertEqual(
            (
                ("cash", Decimal("50")),
                ("uncategorized", Decimal("25")),
                ("fees", Decimal("10")),
                ("groceries", Decimal("-50")),
            ),
            result.category_totals,
        )
        self.assertEqual(
            (
                (date(2026, 1, 1), Decimal("-50")),
                (date(2026, 2, 1), Decimal("10")),
                (date(2026, 3, 1), Decimal("75")),
            ),
            result.monthly_totals,
        )

    def test_filters_and_direct_edits_recalculate_authoritative_values(self) -> None:
        member_b = calculate_dashboard(
            self.transactions,
            replace(self.filters, member_id="member-b", category_id="cash"),
        )
        edited = tuple(
            replace(item, amount=Money(Decimal("80"))) if item.transaction_id == "cash" else item
            for item in self.transactions
        )
        after_edit = calculate_dashboard(
            edited,
            replace(self.filters, member_id="member-b", category_id="cash"),
        )

        self.assertEqual(Decimal("50"), member_b.total_net_spend)
        self.assertEqual(Decimal("80"), after_edit.total_net_spend)
        self.assertEqual(
            Decimal("-50"),
            calculate_dashboard(
                self.transactions,
                DashboardFilters(date(2026, 1, 1), date(2026, 1, 31)),
            ).total_net_spend,
        )
        self.assertEqual(
            Decimal(),
            calculate_dashboard(
                self.transactions,
                replace(self.filters, institution="chase"),
            ).total_net_spend,
        )
        self.assertEqual(
            Decimal(),
            calculate_dashboard(
                self.transactions,
                replace(self.filters, account_id="ending-99999"),
            ).total_net_spend,
        )

    def test_layout_centralizes_filters_and_has_required_native_charts(self) -> None:
        layout = build_dashboard_layout()
        helper_formulas = " ".join(str(value) for value in layout.rows[55])

        self.assertEqual("=EOMONTH(TODAY(),-12)+1", layout.rows[3][1])
        self.assertEqual(
            (
                "Date",
                "Month",
                "Member",
                "Institution",
                "Account",
                "Category",
                "Merchant",
                "Transaction type",
                "Approved",
                "Eligible spend type",
                "Eligible net spend",
                "Cash advance",
                "In current view",
                "View net spend",
                "Uncategorized count",
            ),
            layout.rows[54][:15],
        )
        self.assertIn("purchase|merchant_credit|fee|cash_advance", helper_formulas)
        self.assertIn("MATCH(Transactions!B3:B", helper_formulas)
        self.assertIn('$B$6="All"', helper_formulas)
        self.assertEqual(
            (
                "Net spending by category",
                "Monthly net spending",
                "Member spending by month",
            ),
            tuple(chart.title for chart in layout.charts),
        )
        self.assertEqual("BAR", layout.charts[0].chart_type)
        self.assertEqual(("B6", "B7", "B8", "B9"), tuple(item.cell for item in layout.validations))


if __name__ == "__main__":
    unittest.main()
