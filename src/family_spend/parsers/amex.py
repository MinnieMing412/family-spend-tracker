"""Deterministic parser for text-bearing American Express statements."""

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
_AMOUNT_TOKEN = r"(?:-?\$?-?[\d,]+\.\d{2}|\([\$\d,]+\.\d{2}\))(?:\s*CR)?"
_TRANSACTION_START = re.compile(
    rf"^\s*(?P<transaction_date>{_DATE_TOKEN})(?P<marker>\*)?\s+"
    rf"(?:(?P<posting_date>{_DATE_TOKEN})\s+)?(?P<body>.+?)\s*$",
    re.IGNORECASE,
)
_AMOUNT_AT_END = re.compile(rf"^(?P<description>.*?)\s+(?P<amount>{_AMOUNT_TOKEN})\s*$", re.I)
_TOTAL_LINE = re.compile(
    rf"^\s*Total\s+(?P<label>Payments|Credits|New Charges(?:\s+for\s+.+)?|Fees|Interest Charged)"
    rf"\s+(?P<amount>{_AMOUNT_TOKEN})\s*$",
    re.IGNORECASE,
)
_BILLING_PERIOD_PATTERNS = (
    re.compile(
        rf"(?:Billing|Statement)\s+Period\s*:?\s*(?P<start>{_DATE_TOKEN})\s*"
        rf"(?:-|through|to)\s*(?P<end>{_DATE_TOKEN})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<start>{_DATE_TOKEN})\s*(?:-|through|to)\s*(?P<end>{_DATE_TOKEN})"
        r"\s+Billing\s+Period",
        re.IGNORECASE,
    ),
)
_CLOSING_DATE = re.compile(
    rf"(?:Statement\s+)?Closing\s+Date\s*:?\s*(?P<date>{_DATE_TOKEN})",
    re.IGNORECASE,
)
_ACCOUNT = re.compile(
    r"Account(?:\s+Number)?\s+(?:Ending(?:\s+in)?|ending-)\s*[:#]?\s*[xX*•-]*(?P<digits>\d{4,8})",
    re.IGNORECASE,
)
_CARDHOLDER_PATTERNS = (
    re.compile(r"^\s*Cardmember\s*:\s*(?P<name>.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*New Charges for\s+(?P<name>.+?)\s*$", re.IGNORECASE),
)


@dataclass(slots=True)
class _PendingTransaction:
    """A transaction row awaiting a trailing amount on a continuation line."""

    page_number: int
    line_number: int
    transaction_date: str
    posting_date: str | None
    posting_marker: str | None
    body_lines: list[str]
    section: str
    cardholder: str | None

    @property
    def evidence_ref(self) -> str:
        return f"page-{self.page_number}:line-{self.line_number}"


class AmexStatementParser:
    """Parse AMEX identity, activity sections, totals, and evidence references."""

    def parse(self, source: ValidatedPdf) -> ParseResult:
        """Convert a validated AMEX PDF into the common statement contract."""
        full_text = "\n".join(source.page_texts)
        account_id = self._account_id(full_text, source.source_name)
        start_date, end_date = self._billing_period(full_text, source.source_name)
        closing_date = self._closing_date(full_text, end_date)

        warnings: list[DomainWarning] = []
        totals: list[StatementTotal] = []
        transactions: list[NormalizedTransaction] = []
        pending: _PendingTransaction | None = None
        section = "other"
        cardholder: str | None = None

        for page_number, page_text in enumerate(source.page_texts, start=1):
            for line_number, raw_line in enumerate(page_text.splitlines(), start=1):
                line = " ".join(raw_line.split())
                if not line:
                    continue

                detected_section = self._section_for(line)
                total_match = _TOTAL_LINE.match(line)
                cardholder_match = self._cardholder(line)
                transaction_match = _TRANSACTION_START.match(line)

                if pending is not None and not any(
                    (detected_section, total_match, cardholder_match, transaction_match)
                ):
                    pending.body_lines.append(line)
                    if self._amount_parts(" ".join(pending.body_lines)) is not None:
                        transactions.append(
                            self._build_transaction(
                                source,
                                pending,
                                len(transactions),
                                closing_date,
                                account_id,
                            )
                        )
                        pending = None
                    continue

                if pending is not None:
                    warnings.append(self._incomplete_warning(pending))
                    pending = None

                if total_match is not None:
                    totals.append(self._build_total(total_match))
                    continue
                if detected_section is not None:
                    section = detected_section
                    if section != "new_charges":
                        cardholder = None
                    continue
                if cardholder_match is not None:
                    cardholder = cardholder_match
                    continue
                if transaction_match is None or section == "other":
                    continue

                pending = _PendingTransaction(
                    page_number=page_number,
                    line_number=line_number,
                    transaction_date=transaction_match.group("transaction_date"),
                    posting_date=transaction_match.group("posting_date"),
                    posting_marker=transaction_match.group("marker"),
                    body_lines=[transaction_match.group("body")],
                    section=section,
                    cardholder=cardholder,
                )
                if self._amount_parts(pending.body_lines[0]) is not None:
                    transactions.append(
                        self._build_transaction(
                            source,
                            pending,
                            len(transactions),
                            closing_date,
                            account_id,
                        )
                    )
                    pending = None

        if pending is not None:
            warnings.append(self._incomplete_warning(pending))
        if not transactions:
            raise FamilySpendError(
                f"No AMEX transactions could be parsed: {source.source_name}",
                2,
            )
        if not totals:
            warnings.append(
                DomainWarning(
                    code="amex-reported-totals-missing",
                    message="No AMEX section totals could be extracted.",
                    severity=WarningSeverity.WARNING,
                )
            )

        warning_tuple = tuple(warnings)
        statement = NormalizedStatement(
            statement_id=f"stmt-{source.sha256[:20]}",
            source_name=source.source_name,
            source_hash=source.sha256,
            institution=Institution.AMEX,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            closing_date=closing_date,
            transactions=tuple(transactions),
            reported_totals=tuple(totals),
            warnings=warning_tuple,
        )
        return ParseResult(statement=statement, warnings=warning_tuple)

    @staticmethod
    def _account_id(text: str, source_name: str) -> str:
        match = _ACCOUNT.search(text)
        if match is None:
            raise FamilySpendError(
                f"AMEX masked account identifier is missing: {source_name}",
                2,
            )
        return f"ending-{match.group('digits')}"

    @classmethod
    def _billing_period(cls, text: str, source_name: str) -> tuple[date, date]:
        for pattern in _BILLING_PERIOD_PATTERNS:
            match = pattern.search(text)
            if match is not None:
                end = cls._parse_date(match.group("end"), None)
                return cls._parse_date(match.group("start"), end), end
        raise FamilySpendError(f"AMEX billing period is missing: {source_name}", 2)

    @classmethod
    def _closing_date(cls, text: str, fallback: date) -> date:
        match = _CLOSING_DATE.search(text)
        return cls._parse_date(match.group("date"), fallback) if match else fallback

    @staticmethod
    def _section_for(line: str) -> str | None:
        normalized = line.casefold().strip(":")
        if normalized in {"payments and credits", "payments & credits"}:
            return "payments_credits"
        if normalized in {"new charges", "new activity"}:
            return "new_charges"
        if normalized in {"fees", "fees charged"}:
            return "fees"
        if normalized in {"interest charged", "interest"}:
            return "interest"
        return None

    @staticmethod
    def _cardholder(line: str) -> str | None:
        for pattern in _CARDHOLDER_PATTERNS:
            match = pattern.match(line)
            if match is not None:
                return " ".join(match.group("name").split()).upper()
        return None

    @classmethod
    def _build_total(cls, match: re.Match[str]) -> StatementTotal:
        label = "_".join(match.group("label").casefold().split())
        amount = cls._parse_amount(match.group("amount"))
        amount = -abs(amount) if label.startswith(("payments", "credits")) else abs(amount)
        return StatementTotal(label, Money(amount))

    @classmethod
    def _build_transaction(
        cls,
        source: ValidatedPdf,
        pending: _PendingTransaction,
        index: int,
        closing_date: date,
        account_id: str,
    ) -> NormalizedTransaction:
        combined = " ".join(pending.body_lines)
        amount_parts = cls._amount_parts(combined)
        if amount_parts is None:
            raise AssertionError("transaction must have an amount before it is built")
        description, displayed_amount = amount_parts
        transaction_type = cls._transaction_type(
            pending.section,
            description,
            displayed_amount,
        )
        amount = cls._normalized_amount(displayed_amount, transaction_type)
        transaction_date = cls._parse_date(pending.transaction_date, closing_date)
        posting_date = (
            cls._parse_date(pending.posting_date, closing_date)
            if pending.posting_date
            else None
        )
        metadata = [
            ("evidence_ref", pending.evidence_ref),
            ("statement_section", pending.section),
        ]
        if pending.cardholder:
            metadata.append(("cardholder", pending.cardholder))
        if pending.posting_marker:
            metadata.append(("posting_date_marker", pending.posting_marker))
        stable_key = f"{source.sha256}:{index}:{pending.evidence_ref}"
        transaction_id = f"txn-{hashlib.sha256(stable_key.encode()).hexdigest()[:20]}"
        included_in_spend = transaction_type is not TransactionType.PAYMENT
        return NormalizedTransaction(
            transaction_id=transaction_id,
            institution=Institution.AMEX,
            account_id=account_id,
            member_id=None,
            transaction_date=transaction_date,
            posting_date=posting_date,
            raw_description=description,
            normalized_merchant=description.upper(),
            merchant_location=cls._merchant_location(pending.body_lines),
            amount=Money(amount),
            transaction_type=transaction_type,
            category_id=None,
            included_in_spend=included_in_spend,
            reviewed=False,
            statement_id=f"stmt-{source.sha256[:20]}",
            source_metadata=tuple(metadata),
        )

    @staticmethod
    def _transaction_type(
        section: str,
        description: str,
        amount: Decimal,
    ) -> TransactionType:
        lowered = description.casefold()
        if section == "payments_credits":
            return (
                TransactionType.PAYMENT
                if "payment" in lowered or "autopay" in lowered
                else TransactionType.MERCHANT_CREDIT
            )
        if section == "fees":
            return TransactionType.FEE
        if section == "interest":
            return TransactionType.INTEREST
        if amount < 0 or "credit" in lowered or "refund" in lowered:
            return TransactionType.MERCHANT_CREDIT
        return TransactionType.PURCHASE

    @staticmethod
    def _normalized_amount(amount: Decimal, transaction_type: TransactionType) -> Decimal:
        if transaction_type in {TransactionType.MERCHANT_CREDIT, TransactionType.PAYMENT}:
            return -abs(amount)
        return abs(amount)

    @classmethod
    def _amount_parts(cls, value: str) -> tuple[str, Decimal] | None:
        match = _AMOUNT_AT_END.match(value)
        if match is None or not match.group("description").strip():
            return None
        return " ".join(match.group("description").split()), cls._parse_amount(
            match.group("amount")
        )

    @staticmethod
    def _parse_amount(value: str) -> Decimal:
        normalized = value.strip().upper()
        negative = normalized.endswith("CR") or normalized.startswith("(")
        normalized = normalized.removesuffix("CR").strip()
        normalized = normalized.replace("$", "").replace(",", "")
        if normalized.startswith("(") and normalized.endswith(")"):
            normalized = normalized[1:-1]
        try:
            amount = Decimal(normalized)
        except InvalidOperation as error:
            raise FamilySpendError("AMEX statement contains an invalid amount", 2) from error
        return -abs(amount) if negative else amount

    @staticmethod
    def _parse_date(value: str, reference: date | None) -> date:
        pieces = tuple(int(piece) for piece in value.split("/"))
        if len(pieces) == 3:
            month, day, year = pieces
            year = year + 2000 if year < 100 else year
            return date(year, month, day)
        if reference is None:
            raise FamilySpendError("AMEX statement date is missing a year", 2)
        month, day = pieces
        year = reference.year
        if month > reference.month + 6:
            year -= 1
        return date(year, month, day)

    @staticmethod
    def _merchant_location(lines: list[str]) -> str | None:
        if len(lines) < 2:
            return None
        last_line = lines[-1]
        amount_match = _AMOUNT_AT_END.match(last_line)
        location = amount_match.group("description").strip() if amount_match else last_line
        return location if re.search(r"\b[A-Z]{2}(?:\s|$)", location) else None

    @staticmethod
    def _incomplete_warning(pending: _PendingTransaction) -> DomainWarning:
        return DomainWarning(
            code="amex-partial-transaction-row",
            message="An AMEX transaction row did not contain a parseable amount.",
            severity=WarningSeverity.WARNING,
            evidence_ref=pending.evidence_ref,
        )
