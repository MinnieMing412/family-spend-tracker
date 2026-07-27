from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from family_spend.domain.models import (
    AccountConfig,
    CategoryConfig,
    DomainWarning,
    ImportRecord,
    ImportResult,
    ImportStatus,
    Institution,
    MatchType,
    MemberConfig,
    MerchantRule,
    Money,
    NormalizedStatement,
    NormalizedTransaction,
    TransactionType,
    WarningSeverity,
    WorkbookConfig,
)


def make_transaction(**overrides: Any) -> NormalizedTransaction:
    values: dict[str, Any] = {
        "transaction_id": "txn-1",
        "institution": Institution.AMEX,
        "account_id": "ending-12345",
        "member_id": "member-1",
        "transaction_date": date(2026, 5, 1),
        "posting_date": None,
        "raw_description": "Example merchant",
        "normalized_merchant": "EXAMPLE MERCHANT",
        "merchant_location": None,
        "amount": Money(Decimal("12.34")),
        "transaction_type": TransactionType.PURCHASE,
        "category_id": "dining",
        "included_in_spend": True,
        "reviewed": False,
    }
    values.update(overrides)
    return NormalizedTransaction(**values)


def make_statement(**overrides: Any) -> NormalizedStatement:
    values: dict[str, Any] = {
        "statement_id": "statement-1",
        "source_name": "sample.pdf",
        "source_hash": "a" * 64,
        "institution": Institution.AMEX,
        "account_id": "ending-12345",
        "start_date": date(2026, 4, 1),
        "end_date": date(2026, 5, 1),
        "closing_date": date(2026, 5, 1),
        "transactions": (),
        "reported_totals": (),
        "warnings": (),
    }
    values.update(overrides)
    return NormalizedStatement(**values)


class MoneyContractTests(unittest.TestCase):
    def test_money_rejects_non_finite_values(self) -> None:
        for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                Money(value)

    def test_money_addition_is_exact(self) -> None:
        total = Money(Decimal("0.10")) + Money(Decimal("0.20"))

        self.assertEqual(Money(Decimal("0.30")), total)


class NormalizedTransactionContractTests(unittest.TestCase):
    def test_transaction_rejects_an_unsupported_institution_at_runtime(self) -> None:
        with self.assertRaisesRegex(TypeError, "institution"):
            make_transaction(institution=cast(Any, "unsupported"))

    def test_transaction_rejects_an_unsupported_type_at_runtime(self) -> None:
        with self.assertRaisesRegex(TypeError, "transaction_type"):
            make_transaction(transaction_type=cast(Any, "unsupported"))

    def test_transaction_rejects_a_non_date_at_runtime(self) -> None:
        with self.assertRaisesRegex(TypeError, "transaction_date"):
            make_transaction(transaction_date=cast(Any, "2026-99-99"))

    def test_transaction_rejects_a_datetime_for_a_date_only_field(self) -> None:
        with self.assertRaisesRegex(TypeError, "transaction_date"):
            make_transaction(transaction_date=datetime(2026, 5, 1, 12, 30))

    def test_transaction_rejects_a_non_money_amount_at_runtime(self) -> None:
        with self.assertRaisesRegex(TypeError, "amount"):
            make_transaction(
                amount=cast(Any, "12.34"),
                transaction_type=TransactionType.TRANSFER,
            )

    def test_transaction_rejects_a_full_account_number(self) -> None:
        account_number = "".join(("1234", "5678", "9012", "3456"))

        with self.assertRaisesRegex(ValueError, "masked"):
            make_transaction(account_id=account_number)

    def test_transaction_rejects_an_unmasked_partial_account_number(self) -> None:
        account_number = "".join(("1234", "5678"))

        with self.assertRaisesRegex(ValueError, "masked"):
            make_transaction(account_id=account_number)

    def test_credit_types_require_negative_amounts(self) -> None:
        for transaction_type in (
            TransactionType.MERCHANT_CREDIT,
            TransactionType.PAYMENT,
        ):
            with self.subTest(
                transaction_type=transaction_type
            ), self.assertRaisesRegex(ValueError, "negative"):
                make_transaction(
                    amount=Money(Decimal("81.02")),
                    transaction_type=transaction_type,
                )

    def test_debit_types_require_positive_amounts(self) -> None:
        for transaction_type in (
            TransactionType.PURCHASE,
            TransactionType.FEE,
            TransactionType.INTEREST,
            TransactionType.CASH_ADVANCE,
        ):
            with self.subTest(
                transaction_type=transaction_type
            ), self.assertRaisesRegex(ValueError, "positive"):
                make_transaction(
                    amount=Money(Decimal("-12.34")),
                    transaction_type=transaction_type,
                )


class NormalizedStatementContractTests(unittest.TestCase):
    def test_statement_rejects_an_unsupported_institution_at_runtime(self) -> None:
        with self.assertRaisesRegex(TypeError, "institution"):
            make_statement(institution=cast(Any, "unsupported"))

    def test_statement_rejects_non_date_fields_at_runtime(self) -> None:
        with self.assertRaisesRegex(TypeError, "start_date"):
            make_statement(start_date=cast(Any, "2026-99-99"))

    def test_statement_rejects_a_datetime_for_a_date_only_field(self) -> None:
        with self.assertRaisesRegex(TypeError, "closing_date"):
            make_statement(closing_date=datetime(2026, 5, 1, 12, 30))

    def test_statement_rejects_an_end_date_before_its_start_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "date range"):
            make_statement(
                start_date=date(2026, 5, 1),
                end_date=date(2026, 4, 1),
            )

    def test_statement_rejects_an_unmasked_account_identifier(self) -> None:
        account_number = "".join(("1234", "5678"))

        with self.assertRaisesRegex(ValueError, "masked"):
            make_statement(account_id=account_number)


class WorkbookConfigContractTests(unittest.TestCase):
    def test_account_config_rejects_an_unsupported_institution(self) -> None:
        with self.assertRaisesRegex(TypeError, "institution"):
            AccountConfig(
                account_id="amex-primary",
                institution=cast(Any, "unsupported"),
                masked_identifier="ending-12345",
                default_member_id="member-1",
                display_name="AMEX",
                active=True,
            )

    def test_account_config_rejects_an_unmasked_identifier(self) -> None:
        account_number = "".join(("1234", "5678"))

        with self.assertRaisesRegex(ValueError, "masked"):
            AccountConfig(
                account_id="amex-primary",
                institution=Institution.AMEX,
                masked_identifier=account_number,
                default_member_id="member-1",
                display_name="AMEX",
                active=True,
            )

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
                        account_id="amex-primary",
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

    def test_rule_rejects_an_unsupported_match_type(self) -> None:
        with self.assertRaisesRegex(TypeError, "match_type"):
            MerchantRule(
                rule_id="rule-1",
                match_type=cast(Any, "unsupported"),
                match_value="EXAMPLE MERCHANT",
                normalized_merchant="EXAMPLE MERCHANT",
                category_id="dining",
                priority=1,
                active=True,
            )


class ConstrainedValueContractTests(unittest.TestCase):
    def test_warning_rejects_an_unsupported_severity(self) -> None:
        with self.assertRaisesRegex(TypeError, "severity"):
            DomainWarning(
                code="parse-warning",
                message="Example warning",
                severity=cast(Any, "unsupported"),
            )

    def test_import_record_rejects_an_unsupported_status(self) -> None:
        with self.assertRaisesRegex(TypeError, "status"):
            ImportRecord(
                import_id="import-1",
                statement_hash="a" * 64,
                status=cast(Any, "unsupported"),
                transaction_ids=(),
            )

    def test_import_result_rejects_an_unsupported_status(self) -> None:
        with self.assertRaisesRegex(TypeError, "status"):
            ImportResult(
                import_id="import-1",
                status=cast(Any, "unsupported"),
                transaction_ids=(),
                message="Example",
            )

    def test_import_status_accepts_a_supported_value(self) -> None:
        result = ImportResult(
            import_id="import-1",
            status=ImportStatus.COMPLETE,
            transaction_ids=(),
            message="Complete",
        )

        self.assertEqual(ImportStatus.COMPLETE, result.status)
        self.assertEqual(WarningSeverity.WARNING, WarningSeverity("warning"))


if __name__ == "__main__":
    unittest.main()
