"""Deterministic parser for supported Chase consumer credit-card statements."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
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

_DATE_TOKEN = r"\d{1,2}/\d{1,2}(?:/\d{2,4})?"
_AMOUNT_TOKEN = r"[+-]?\$?[\d,]+\.\d{2}-?"
_TRANSACTION = re.compile(
    rf"^\s*(?P<date>{_DATE_TOKEN})\s+(?P<description>.+?)\s+"
    rf"(?P<amount>{_AMOUNT_TOKEN})\s*$",
    re.IGNORECASE,
)
_PERIOD = re.compile(
    rf"Opening/Closing\s+Date\s+(?P<start>{_DATE_TOKEN})\s*[-\u2013]\s*"
    rf"(?P<end>{_DATE_TOKEN})",
    re.IGNORECASE,
)
_ACCOUNT = re.compile(
    r"Account\s+Number\s*:\s*(?:[X*•]+\s*)+(?P<digits>\d{4,8})",
    re.IGNORECASE,
)
_SUMMARY_TOTALS = (
    (
        "payments_and_other_credits",
        re.compile(rf"Payments?\s*,?\s*Credits?\s+(?P<amount>{_AMOUNT_TOKEN})", re.I),
    ),
    (
        "new_charges",
        re.compile(rf"Purchases\s+(?P<amount>{_AMOUNT_TOKEN})", re.I),
    ),
    (
        "cash_advances",
        re.compile(rf"Cash\s+Advances\s+(?P<amount>{_AMOUNT_TOKEN})", re.I),
    ),
    (
        "balance_transfers",
        re.compile(rf"Balance\s+Transfers\s+(?P<amount>{_AMOUNT_TOKEN})", re.I),
    ),
    (
        "fees",
        re.compile(rf"Fees\s+Charged\s+(?P<amount>{_AMOUNT_TOKEN})", re.I),
    ),
    (
        "interest_charged",
        re.compile(rf"Interest\s+Charged\s+(?P<amount>{_AMOUNT_TOKEN})", re.I),
    ),
)


@dataclass(frozen=True, slots=True)
class _ParsedRow:
    page_number: int
    line_number: int
    transaction_date: str
    description: str
    displayed_amount: Decimal
    section: str

    @property
    def evidence_ref(self) -> str:
        return f"page-{self.page_number}:line-{self.line_number}"


class ChaseStatementParser:
    """Parse Chase account summary and activity into the common contract."""

    def parse(self, source: ValidatedPdf) -> ParseResult:
        full_text = "\n".join(source.page_texts)
        account_id = self._account_id(full_text, source.source_name)
        start_date, end_date = self._period(full_text, source.source_name)
        totals = self._totals(full_text)
        rows, warnings = self._activity_rows(source)
        if not rows:
            raise FamilySpendError(
                "Unsupported Chase credit-card layout: "
                f"no account activity rows were recognized in {source.source_name}",
                2,
            )
        transactions = tuple(
            self._transaction(source, row, index, account_id, end_date)
            for index, row in enumerate(rows)
        )
        if not totals:
            warnings.append(
                DomainWarning(
                    code="chase-reported-totals-missing",
                    message="No Chase account-summary totals could be extracted.",
                    severity=WarningSeverity.WARNING,
                )
            )
        warning_tuple = tuple(warnings)
        statement = NormalizedStatement(
            statement_id=f"stmt-{source.sha256[:20]}",
            source_name=source.source_name,
            source_hash=source.sha256,
            institution=Institution.CHASE,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            closing_date=end_date,
            transactions=transactions,
            reported_totals=totals,
            warnings=warning_tuple,
        )
        return ParseResult(statement, warning_tuple)

    @staticmethod
    def _account_id(text: str, source_name: str) -> str:
        match = _ACCOUNT.search(text)
        if match is None:
            raise FamilySpendError(
                "Unsupported Chase credit-card layout: "
                f"masked account identifier is missing in {source_name}",
                2,
            )
        return f"ending-{match.group('digits')[-4:]}"

    @classmethod
    def _period(cls, text: str, source_name: str) -> tuple[date, date]:
        match = _PERIOD.search(text)
        if match is None:
            raise FamilySpendError(
                "Unsupported Chase credit-card layout: "
                f"opening/closing dates are missing in {source_name}",
                2,
            )
        end = cls._parse_date(match.group("end"), None)
        return cls._parse_date(match.group("start"), end), end

    @classmethod
    def _totals(cls, text: str) -> tuple[StatementTotal, ...]:
        summary_start = text.casefold().find("account summary")
        if summary_start < 0:
            return ()
        summary_end = text.casefold().find("your account messages", summary_start)
        summary = text[summary_start : summary_end if summary_end >= 0 else None]
        totals: list[StatementTotal] = []
        for section, pattern in _SUMMARY_TOTALS:
            match = pattern.search(summary)
            if match is not None:
                totals.append(
                    StatementTotal(section, Money(cls._parse_amount(match.group("amount"))))
                )
        return tuple(totals)

    @classmethod
    def _activity_rows(
        cls,
        source: ValidatedPdf,
    ) -> tuple[list[_ParsedRow], list[DomainWarning]]:
        rows: list[_ParsedRow] = []
        warnings: list[DomainWarning] = []
        in_activity = False
        section = "other"
        for page_number, page_text in enumerate(source.page_texts, start=1):
            for line_number, raw_line in enumerate(page_text.splitlines(), start=1):
                line = " ".join(raw_line.split())
                if not line:
                    continue
                normalized = line.casefold().strip(":")
                if normalized == "account activity":
                    in_activity = True
                    continue
                detected_section = cls._section_for(normalized)
                if detected_section is not None:
                    section = detected_section
                    continue
                if not in_activity or section == "other":
                    continue
                match = _TRANSACTION.match(line)
                if match is not None:
                    rows.append(
                        _ParsedRow(
                            page_number,
                            line_number,
                            match.group("date"),
                            cls._safe_description(match.group("description")),
                            cls._parse_amount(match.group("amount")),
                            section,
                        )
                    )
                elif re.match(rf"^{_DATE_TOKEN}\b", line):
                    warnings.append(
                        DomainWarning(
                            code="chase-partial-transaction-row",
                            message="A Chase activity row did not contain a parseable amount.",
                            severity=WarningSeverity.WARNING,
                            evidence_ref=f"page-{page_number}:line-{line_number}",
                        )
                    )
        return rows, warnings

    @staticmethod
    def _section_for(normalized: str) -> str | None:
        if normalized in {"payments and other credits", "payment and other credits"}:
            return "payments_and_other_credits"
        if normalized in {"purchase", "purchases"}:
            return "new_charges"
        if normalized in {"cash advance", "cash advances"}:
            return "cash_advances"
        if normalized in {"balance transfer", "balance transfers"}:
            return "balance_transfers"
        if normalized in {"fees charged", "fees"}:
            return "fees"
        if normalized in {"interest charged", "interest charges"}:
            return "interest"
        return None

    @classmethod
    def _transaction(
        cls,
        source: ValidatedPdf,
        row: _ParsedRow,
        index: int,
        account_id: str,
        closing_date: date,
    ) -> NormalizedTransaction:
        transaction_type = cls._transaction_type(
            row.section,
            row.description,
            row.displayed_amount,
        )
        amount = cls._normalized_amount(row.displayed_amount, transaction_type)
        stable_key = f"{source.sha256}:{index}:{row.evidence_ref}"
        transaction_id = f"txn-{hashlib.sha256(stable_key.encode()).hexdigest()[:20]}"
        return NormalizedTransaction(
            transaction_id=transaction_id,
            institution=Institution.CHASE,
            account_id=account_id,
            member_id=None,
            transaction_date=cls._parse_date(row.transaction_date, closing_date),
            posting_date=None,
            raw_description=row.description,
            normalized_merchant=row.description.upper(),
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
                ("evidence_ref", row.evidence_ref),
                ("statement_section", row.section),
            ),
        )

    @staticmethod
    def _transaction_type(
        section: str,
        description: str,
        amount: Decimal,
    ) -> TransactionType:
        lowered = description.casefold()
        if section == "payments_and_other_credits":
            return (
                TransactionType.PAYMENT
                if "payment" in lowered or "autopay" in lowered
                else TransactionType.MERCHANT_CREDIT
            )
        if section == "cash_advances":
            return TransactionType.CASH_ADVANCE
        if section == "balance_transfers":
            return TransactionType.TRANSFER
        if section == "fees":
            return TransactionType.FEE
        if section == "interest":
            return TransactionType.INTEREST
        if amount < 0 or any(token in lowered for token in ("credit", "refund", "return")):
            return TransactionType.MERCHANT_CREDIT
        return TransactionType.PURCHASE

    @staticmethod
    def _normalized_amount(amount: Decimal, transaction_type: TransactionType) -> Decimal:
        if transaction_type in {TransactionType.PAYMENT, TransactionType.MERCHANT_CREDIT}:
            return -abs(amount)
        if transaction_type in {
            TransactionType.PURCHASE,
            TransactionType.CASH_ADVANCE,
            TransactionType.FEE,
            TransactionType.INTEREST,
        }:
            return abs(amount)
        return amount

    @staticmethod
    def _safe_description(value: str) -> str:
        description = re.sub(r"\*[A-Z0-9]{8,}\b", "", value, flags=re.IGNORECASE)
        description = re.sub(r"\b\d{7,}\b", "", description)
        return " ".join(description.split())

    @staticmethod
    def _parse_amount(value: str) -> Decimal:
        normalized = value.strip().replace("$", "").replace(",", "")
        negative = normalized.startswith("-") or normalized.endswith("-")
        normalized = normalized.removeprefix("+").removeprefix("-").removesuffix("-")
        try:
            amount = Decimal(normalized)
        except InvalidOperation as error:
            raise FamilySpendError("Chase statement contains an invalid amount", 2) from error
        return -abs(amount) if negative else amount

    @staticmethod
    def _parse_date(value: str, reference: date | None) -> date:
        pieces = tuple(int(piece) for piece in value.split("/"))
        if len(pieces) == 3:
            month, day, year = pieces
            year = year + 2000 if year < 100 else year
            return date(year, month, day)
        if reference is None:
            raise FamilySpendError("Chase statement date is missing a year", 2)
        month, day = pieces
        year = reference.year
        if month > reference.month + 6:
            year -= 1
        return date(year, month, day)
