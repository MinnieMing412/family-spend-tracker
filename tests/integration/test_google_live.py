from __future__ import annotations

import os
import time
import unittest
from collections.abc import Callable
from datetime import date

import pytest

from family_spend.adapters.google import GoogleApiSheetsClient, GoogleWorkbookFactory
from family_spend.adapters.local import FileCredentialStore, default_application_directory

WORKBOOK_ID = os.environ.get("FAMILY_SPEND_GOOGLE_INTEGRATION_WORKBOOK_ID")
_GOOGLE_SHEETS_EPOCH = date(1899, 12, 30)
_QA_START_DATE = (date(2026, 1, 1) - _GOOGLE_SHEETS_EPOCH).days
_QA_FEBRUARY_START_DATE = (date(2026, 2, 1) - _GOOGLE_SHEETS_EPOCH).days
_QA_END_DATE = (date(2026, 3, 31) - _GOOGLE_SHEETS_EPOCH).days

_MEMBER_ROWS = (
    ("qa-member-a", "QA Member A", "", True),
    ("qa-member-b", "QA Member B", "", True),
)
_ACCOUNT_ROWS = (
    ("ending-12345", "amex", "ending-12345", "qa-member-a", "QA Card", True),
    ("ending-99999", "chase", "ending-99999", "qa-member-b", "QA Empty Card", True),
)
_TRANSACTION_ROWS = (
    (
        "qa-purchase",
        "qa-fingerprint-purchase",
        "qa-import",
        "amex",
        "ending-12345",
        "qa-member-a",
        "2026-01-05",
        "",
        "QA MARKET",
        "QA MARKET",
        "",
        "100",
        "purchase",
        "groceries",
        True,
        True,
        "2026-04-01T12:00:00+00:00",
    ),
    (
        "qa-refund",
        "qa-fingerprint-refund",
        "qa-import",
        "amex",
        "ending-12345",
        "qa-member-a",
        "2026-01-10",
        "",
        "QA MARKET REFUND",
        "QA MARKET",
        "",
        "-150",
        "merchant_credit",
        "groceries",
        True,
        True,
        "2026-04-01T12:00:00+00:00",
    ),
    (
        "qa-fee",
        "qa-fingerprint-fee",
        "qa-import",
        "amex",
        "ending-12345",
        "qa-member-a",
        "2026-02-01",
        "",
        "QA BANK FEE",
        "QA BANK FEE",
        "",
        "10",
        "fee",
        "fees",
        True,
        True,
        "2026-04-01T12:00:00+00:00",
    ),
    (
        "qa-cash",
        "qa-fingerprint-cash",
        "qa-import",
        "amex",
        "ending-12345",
        "qa-member-b",
        "2026-03-01",
        "",
        "QA ATM",
        "QA ATM",
        "",
        "50",
        "cash_advance",
        "cash",
        True,
        True,
        "2026-04-01T12:00:00+00:00",
    ),
    (
        "qa-uncategorized",
        "qa-fingerprint-uncategorized",
        "qa-import",
        "amex",
        "ending-12345",
        "qa-member-b",
        "2026-03-05",
        "",
        "QA UNKNOWN",
        "QA UNKNOWN",
        "",
        "25",
        "purchase",
        "uncategorized",
        True,
        True,
        "2026-04-01T12:00:00+00:00",
    ),
    (
        "qa-interest",
        "qa-fingerprint-interest",
        "qa-import",
        "amex",
        "ending-12345",
        "qa-member-a",
        "2026-02-02",
        "",
        "QA INTEREST",
        "QA INTEREST",
        "",
        "20",
        "interest",
        "",
        False,
        True,
        "2026-04-01T12:00:00+00:00",
    ),
    (
        "qa-other",
        "qa-fingerprint-other",
        "qa-import",
        "amex",
        "ending-12345",
        "qa-member-a",
        "2026-02-02",
        "",
        "QA OTHER",
        "QA OTHER",
        "",
        "40",
        "other",
        "",
        False,
        True,
        "2026-04-01T12:00:00+00:00",
    ),
    (
        "qa-rewards",
        "qa-fingerprint-rewards",
        "qa-import",
        "amex",
        "ending-12345",
        "qa-member-a",
        "2026-02-02",
        "",
        "QA REWARDS",
        "QA REWARDS",
        "",
        "15",
        "rewards",
        "",
        False,
        True,
        "2026-04-01T12:00:00+00:00",
    ),
    (
        "qa-payment",
        "qa-fingerprint-payment",
        "qa-import",
        "amex",
        "ending-12345",
        "qa-member-a",
        "2026-02-03",
        "",
        "QA PAYMENT",
        "QA PAYMENT",
        "",
        "-500",
        "payment",
        "",
        False,
        True,
        "2026-04-01T12:00:00+00:00",
    ),
    (
        "qa-transfer",
        "qa-fingerprint-transfer",
        "qa-import",
        "amex",
        "ending-12345",
        "qa-member-a",
        "2026-02-03",
        "",
        "QA TRANSFER",
        "QA TRANSFER",
        "",
        "70",
        "transfer",
        "",
        False,
        True,
        "2026-04-01T12:00:00+00:00",
    ),
    (
        "qa-unapproved",
        "qa-fingerprint-unapproved",
        "qa-import",
        "amex",
        "ending-12345",
        "qa-member-a",
        "2026-02-04",
        "",
        "QA UNAPPROVED",
        "QA UNAPPROVED",
        "",
        "1000",
        "purchase",
        "shopping",
        True,
        False,
        "2026-04-01T12:00:00+00:00",
    ),
)


def _wait_until(assertion: Callable[[], None], *, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            assertion()
            return
        except AssertionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)


@unittest.skipUnless(
    WORKBOOK_ID,
    "set FAMILY_SPEND_GOOGLE_INTEGRATION_WORKBOOK_ID to a disposable workbook",
)
@pytest.mark.integration
class LiveGoogleWorkbookIntegrationTests(unittest.TestCase):
    def test_disposable_workbook_matches_the_shared_gateway_contract(self) -> None:
        credential_store = FileCredentialStore(default_application_directory() / "credentials.json")
        client = GoogleApiSheetsClient(credential_store)
        gateway = GoogleWorkbookFactory(client).connect(str(WORKBOOK_ID))

        gateway.validate_schema()
        existing_transactions = client.read_rows(gateway.workbook_id, "Transactions")[2:]
        self.assertTrue(
            not existing_transactions
            or tuple(str(row[0]) for row in existing_transactions)
            == tuple(str(row[0]) for row in _TRANSACTION_ROWS),
            "integration workbook must be disposable and contain no non-QA transactions",
        )
        client.write_rows(gateway.workbook_id, "Members", 3, _MEMBER_ROWS)
        client.write_rows(gateway.workbook_id, "Accounts", 3, _ACCOUNT_ROWS)
        client.write_rows(gateway.workbook_id, "Transactions", 3, _TRANSACTION_ROWS)
        self.addCleanup(gateway.provision_dashboard)
        self.addCleanup(
            client.write_rows,
            gateway.workbook_id,
            "Transactions",
            3,
            _TRANSACTION_ROWS,
        )
        gateway.provision_dashboard()
        client.write_rows(
            gateway.workbook_id,
            "Dashboard",
            4,
            (("Start date", _QA_START_DATE), ("End date", _QA_END_DATE)),
        )

        def assert_dashboard_values() -> None:
            dashboard = client.read_rows(gateway.workbook_id, "Dashboard")
            self.assertEqual("$35.00", dashboard[4][3])
            self.assertEqual("cash", dashboard[4][7])
            self.assertEqual("1", str(dashboard[4][9]))
            self.assertEqual("1", str(dashboard[7][9]))
            support = dashboard[55 : 55 + len(_TRANSACTION_ROWS)]
            expected = (
                ("purchase", "1", "TRUE", "$100.00"),
                ("merchant_credit", "1", "TRUE", "-$150.00"),
                ("fee", "1", "TRUE", "$10.00"),
                ("cash_advance", "1", "TRUE", "$50.00"),
                ("purchase", "1", "TRUE", "$25.00"),
                ("interest", "1", "FALSE", "$0.00"),
                ("other", "1", "FALSE", "$0.00"),
                ("rewards", "1", "FALSE", "$0.00"),
                ("payment", "1", "FALSE", "$0.00"),
                ("transfer", "1", "FALSE", "$0.00"),
                ("purchase", "0", "TRUE", "$0.00"),
            )
            self.assertEqual(
                expected,
                tuple((str(row[7]), str(row[8]), str(row[9]), str(row[10])) for row in support),
            )

        _wait_until(assert_dashboard_values)
        self.assertEqual(
            (
                "Net spending by category",
                "Monthly net spending",
                "Member spending by month",
            ),
            gateway.dashboard_chart_titles(),
        )

        client.write_rows(gateway.workbook_id, "Dashboard", 6, (("Member", "qa-member-b"),))

        def assert_member_filter() -> None:
            dashboard = client.read_rows(gateway.workbook_id, "Dashboard")
            self.assertEqual("$75.00", dashboard[4][3])
            self.assertEqual(("cash", "$50.00"), dashboard[55][16:18])

        _wait_until(assert_member_filter)

        filter_cases = (
            (6, "Member", "All", "$35.00"),
            (7, "Institution", "chase", "$0.00"),
            (7, "Institution", "All", "$35.00"),
            (8, "Account", "ending-99999", "$0.00"),
            (8, "Account", "All", "$35.00"),
            (9, "Category", "groceries", "-$50.00"),
            (9, "Category", "All", "$35.00"),
            (4, "Start date", _QA_FEBRUARY_START_DATE, "$85.00"),
        )
        for row_number, label, value, expected_total in filter_cases:
            client.write_rows(
                gateway.workbook_id,
                "Dashboard",
                row_number,
                ((label, value),),
            )

            def assert_filter_total(expected: str = expected_total) -> None:
                dashboard = client.read_rows(gateway.workbook_id, "Dashboard")
                self.assertEqual(expected, dashboard[4][3])

            _wait_until(assert_filter_total)

        edited_cash = list(_TRANSACTION_ROWS[3])
        edited_cash[11] = "80"
        client.write_rows(gateway.workbook_id, "Transactions", 6, (tuple(edited_cash),))

        def assert_direct_edit() -> None:
            dashboard = client.read_rows(gateway.workbook_id, "Dashboard")
            self.assertEqual("$115.00", dashboard[4][3])

        _wait_until(assert_direct_edit)

        edited_cash = list(_TRANSACTION_ROWS[3])
        edited_cash[13] = "groceries"
        client.write_rows(gateway.workbook_id, "Transactions", 6, (tuple(edited_cash),))

        def assert_category_edit() -> None:
            dashboard = client.read_rows(gateway.workbook_id, "Dashboard")
            self.assertEqual("groceries", dashboard[4][7])

        _wait_until(assert_category_edit)

        edited_cash = list(_TRANSACTION_ROWS[3])
        edited_cash[9] = "QA ATM EDITED"
        client.write_rows(gateway.workbook_id, "Transactions", 6, (tuple(edited_cash),))

        def assert_merchant_edit() -> None:
            dashboard = client.read_rows(gateway.workbook_id, "Dashboard")
            self.assertEqual("QA ATM EDITED", dashboard[13][0])

        _wait_until(assert_merchant_edit)

        edited_cash = list(_TRANSACTION_ROWS[3])
        edited_cash[5] = "qa-member-a"
        client.write_rows(gateway.workbook_id, "Transactions", 6, (tuple(edited_cash),))
        client.write_rows(gateway.workbook_id, "Dashboard", 6, (("Member", "qa-member-b"),))

        def assert_member_edit() -> None:
            dashboard = client.read_rows(gateway.workbook_id, "Dashboard")
            self.assertEqual("$25.00", dashboard[4][3])

        _wait_until(assert_member_edit)

        edited_cash = list(_TRANSACTION_ROWS[3])
        edited_cash[12] = "other"
        edited_cash[14] = False
        client.write_rows(gateway.workbook_id, "Transactions", 6, (tuple(edited_cash),))
        client.write_rows(gateway.workbook_id, "Dashboard", 6, (("Member", "All"),))

        def assert_type_edit() -> None:
            dashboard = client.read_rows(gateway.workbook_id, "Dashboard")
            self.assertEqual("$35.00", dashboard[4][3])
            self.assertEqual("0", str(dashboard[7][9]))

        _wait_until(assert_type_edit)

        client.write_rows(gateway.workbook_id, "Transactions", 6, (_TRANSACTION_ROWS[3],))
        gateway.provision_dashboard()
        self.assertEqual(3, len(gateway.dashboard_chart_titles()))


if __name__ == "__main__":
    unittest.main()
