"""Parser for text-bearing Bank of America consumer deposit statements."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from family_spend.domain.models import (
    DomainWarning,
    Institution,
    Money,
    NormalizedStatement,
    NormalizedTransaction,
    ParseResult,
    StatementTotal,
    TransactionType,
    WarningSeverity,
)
from family_spend.errors import FamilySpendError
from family_spend.ports import ValidatedPdf

_NUMERIC_DATE = r"\d{1,2}/\d{1,2}/\d{2,4}"
_AMOUNT = r"-?\$?[\d,]+\.\d{2}"
_PERIOD = re.compile(
    r"\bfor\s+(?P<start>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\s+to\s+"
    r"(?P<end>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
_ACCOUNT = re.compile(
    r"Account\s+number\s*:\s*(?P<value>\d{4}(?:\s+\d{4}){1,3})\b",
    re.IGNORECASE,
)
_ROW_START = re.compile(rf"(?P<date>{_NUMERIC_DATE})", re.IGNORECASE)
_AMOUNT_VALUE = re.compile(_AMOUNT, re.IGNORECASE)
_SUMMARY_TOTALS = (
    ("deposits_and_other_additions", "Deposits and other additions"),
    ("withdrawals_and_other_subtractions", "Withdrawals and other subtractions"),
    ("checks", "Checks"),
    ("fees", "Service fees"),
)


class BankOfAmericaDepositStatementParser:
    """Normalize BOA deposit cash flow into the shared transaction contract."""

    def parse(self, source: ValidatedPdf) -> ParseResult:
        page_texts = tuple(self._compact(page) for page in source.page_texts)
        full_text = " ".join(page_texts)
        account_id = self._account_id(full_text, source.source_name)
        start_date, end_date = self._period(full_text, source.source_name)
        totals = self._totals(full_text)

        transactions: list[NormalizedTransaction] = []
        for page_number, page_text in enumerate(page_texts, start=1):
            transactions.extend(
                self._transactions_for_section(
                    source,
                    page_text,
                    page_number,
                    "Deposits and other additions",
                    "Total deposits and other additions",
                    "deposits_and_other_additions",
                    account_id,
                    len(transactions),
                )
            )
            transactions.extend(
                self._transactions_for_section(
                    source,
                    page_text,
                    page_number,
                    "Withdrawals and other subtractions",
                    "Total withdrawals and other subtractions",
                    "withdrawals_and_other_subtractions",
                    account_id,
                    len(transactions),
                )
            )

        if not transactions:
            raise FamilySpendError(
                "Unsupported Bank of America deposit layout: "
                f"no transaction rows were recognized in {source.source_name}",
                2,
            )
        warnings: tuple[DomainWarning, ...] = ()
        if not totals:
            warnings = (
                DomainWarning(
                    code="boa-deposit-reported-totals-missing",
                    message="No Bank of America deposit summary totals could be extracted.",
                    severity=WarningSeverity.WARNING,
                ),
            )
        statement = NormalizedStatement(
            statement_id=f"stmt-{source.sha256[:20]}",
            source_name=source.source_name,
            source_hash=source.sha256,
            institution=Institution.BANK_OF_AMERICA,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            closing_date=end_date,
            transactions=tuple(transactions),
            reported_totals=totals,
            warnings=warnings,
        )
        return ParseResult(statement, warnings)

    @staticmethod
    def matches(text: str) -> bool:
        lowered = text.casefold()
        return (
            "bank deposit accounts" in lowered
            or (
                "deposits and other additions" in lowered
                and "withdrawals and other subtractions" in lowered
            )
        )

    @staticmethod
    def _compact(value: str) -> str:
        return " ".join(value.split())

    @staticmethod
    def _account_id(text: str, source_name: str) -> str:
        match = _ACCOUNT.search(text)
        if match is None:
            raise FamilySpendError(
                "Unsupported Bank of America deposit layout: "
                f"account number is missing in {source_name}",
                2,
            )
        digits = "".join(character for character in match.group("value") if character.isdigit())
        return f"ending-{digits[-4:]}"

    @staticmethod
    def _period(text: str, source_name: str) -> tuple[date, date]:
        match = _PERIOD.search(text)
        if match is None:
            raise FamilySpendError(
                "Unsupported Bank of America deposit layout: "
                f"statement period is missing in {source_name}",
                2,
            )
        return (
            datetime.strptime(match.group("start"), "%B %d, %Y").date(),
            datetime.strptime(match.group("end"), "%B %d, %Y").date(),
        )

    @classmethod
    def _totals(cls, text: str) -> tuple[StatementTotal, ...]:
        totals: list[StatementTotal] = []
        summary_end = text.casefold().find("ending balance")
        summary = text[:summary_end] if summary_end >= 0 else text
        for section, label in _SUMMARY_TOTALS:
            match = re.search(
                rf"{re.escape(label)}\s*(?P<amount>{_AMOUNT})",
                summary,
                re.IGNORECASE,
            )
            if match is not None:
                totals.append(
                    StatementTotal(
                        section,
                        Money(cls._parse_amount(match.group("amount"))),
                    )
                )
        return tuple(totals)

    @classmethod
    def _transactions_for_section(
        cls,
        source: ValidatedPdf,
        page_text: str,
        page_number: int,
        heading: str,
        total_heading: str,
        section: str,
        account_id: str,
        start_index: int,
    ) -> tuple[NormalizedTransaction, ...]:
        lowered = page_text.casefold()
        end = lowered.rfind(total_heading.casefold())
        if end < 0:
            return ()
        start = lowered.rfind(heading.casefold(), 0, end)
        if start < 0:
            return ()
        body = page_text[start + len(heading) : end]
        rows: list[NormalizedTransaction] = []
        row_starts = tuple(_ROW_START.finditer(body))
        for offset, match in enumerate(row_starts):
            row_end = (
                row_starts[offset + 1].start()
                if offset + 1 < len(row_starts)
                else len(body)
            )
            row_body = body[match.end() : row_end].strip()
            amount_matches = tuple(_AMOUNT_VALUE.finditer(row_body))
            if not amount_matches:
                continue
            amount_match = amount_matches[-1]
            raw_amount = cls._parse_amount(amount_match.group())
            description = cls._safe_description(row_body[: amount_match.start()])
            if not description:
                continue
            transaction_type = cls._transaction_type(section, description)
            amount = cls._normalized_amount(raw_amount, transaction_type)
            evidence_ref = f"page-{page_number}:row-{offset + 1}"
            stable_key = f"{source.sha256}:{start_index + offset}:{evidence_ref}"
            transaction_id = f"txn-{hashlib.sha256(stable_key.encode()).hexdigest()[:20]}"
            rows.append(
                NormalizedTransaction(
                    transaction_id=transaction_id,
                    institution=Institution.BANK_OF_AMERICA,
                    account_id=account_id,
                    member_id=None,
                    transaction_date=cls._parse_numeric_date(match.group("date")),
                    posting_date=None,
                    raw_description=description,
                    normalized_merchant=description.upper(),
                    merchant_location=None,
                    amount=Money(amount),
                    transaction_type=transaction_type,
                    category_id=None,
                    included_in_spend=transaction_type
                    not in {
                        TransactionType.PAYMENT,
                        TransactionType.TRANSFER,
                        TransactionType.REWARDS,
                    },
                    reviewed=False,
                    statement_id=f"stmt-{source.sha256[:20]}",
                    source_metadata=(
                        ("evidence_ref", evidence_ref),
                        ("statement_section", section),
                        ("statement_amount", str(raw_amount)),
                    ),
                )
            )
        return tuple(rows)

    @staticmethod
    def _safe_description(value: str) -> str:
        description = " ".join(value.split())
        if description.casefold().startswith("zelle payment"):
            return "ZELLE PAYMENT"
        description = re.split(
            r"\s+(?:CONF#|ID:|INDN:|CO\s*ID:|COID:)",
            description,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        description = re.sub(r"\b\d{7,}\b", "", description)
        description = re.sub(
            r"\b(?=[A-Z0-9]{8,}\b)(?=[A-Z0-9]*\d)[A-Z0-9]+\b",
            "",
            description,
            flags=re.IGNORECASE,
        )
        return " ".join(description.split())

    @staticmethod
    def _transaction_type(section: str, description: str) -> TransactionType:
        if section == "deposits_and_other_additions":
            return TransactionType.TRANSFER
        lowered = description.casefold()
        if any(token in lowered for token in ("autopay", "ach pmt", "credit crd")):
            return TransactionType.PAYMENT
        if any(token in lowered for token in ("trnsfr", "transfer", "xfer")):
            return TransactionType.TRANSFER
        if any(token in lowered for token in ("atm withdrawal", "cash withdrawal")):
            return TransactionType.CASH_ADVANCE
        return TransactionType.PURCHASE

    @staticmethod
    def _normalized_amount(
        amount: Decimal,
        transaction_type: TransactionType,
    ) -> Decimal:
        if transaction_type is TransactionType.PURCHASE:
            return abs(amount)
        if transaction_type is TransactionType.CASH_ADVANCE:
            return abs(amount)
        if transaction_type is TransactionType.PAYMENT:
            return -abs(amount)
        return amount

    @staticmethod
    def _parse_amount(value: str) -> Decimal:
        try:
            return Decimal(value.replace("$", "").replace(",", ""))
        except InvalidOperation as error:
            raise FamilySpendError(
                "Bank of America deposit statement contains an invalid amount",
                2,
            ) from error

    @staticmethod
    def _parse_numeric_date(value: str) -> date:
        date_format = "%m/%d/%Y" if len(value.rsplit("/", 1)[-1]) == 4 else "%m/%d/%y"
        return datetime.strptime(value, date_format).date()
