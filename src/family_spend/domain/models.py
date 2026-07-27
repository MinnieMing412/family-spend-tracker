from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


def _validate_masked_account_identifier(value: str) -> None:
    if not isinstance(value, str):
        raise TypeError("masked account identifier must be a string")
    digit_count = sum(character.isdigit() for character in value)
    marker_present = any(
        marker in value.lower() for marker in ("ending", "*", "x", "•", "…")
    )
    if not marker_present or not 4 <= digit_count <= 8:
        raise ValueError("account identifier must contain only a masked account identifier")


class Institution(StrEnum):
    AMEX = "amex"
    BANK_OF_AMERICA = "bank_of_america"
    CHASE = "chase"


class TransactionType(StrEnum):
    PURCHASE = "purchase"
    MERCHANT_CREDIT = "merchant_credit"
    FEE = "fee"
    INTEREST = "interest"
    PAYMENT = "payment"
    TRANSFER = "transfer"
    CASH_ADVANCE = "cash_advance"
    REWARDS = "rewards"
    OTHER = "other"


_POSITIVE_TRANSACTION_TYPES = frozenset(
    {
        TransactionType.PURCHASE,
        TransactionType.FEE,
        TransactionType.INTEREST,
        TransactionType.CASH_ADVANCE,
    }
)
_NEGATIVE_TRANSACTION_TYPES = frozenset(
    {
        TransactionType.MERCHANT_CREDIT,
        TransactionType.PAYMENT,
    }
)


class WarningSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class MatchType(StrEnum):
    EXACT = "exact"
    CONTAINS = "contains"


class ReconciliationStatus(StrEnum):
    MATCHED = "matched"
    DISCREPANCY = "discrepancy"
    OVERRIDDEN = "overridden"
    UNAVAILABLE = "unavailable"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    CANCELLED = "cancelled"


class ImportStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str = "USD"

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("money amount must be a Decimal")
        if not self.amount.is_finite():
            raise ValueError("money amount must be finite")
        if self.currency != "USD":
            raise ValueError("v1 supports USD only")

    def __add__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError("cannot add money in different currencies")
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError("cannot subtract money in different currencies")
        return Money(self.amount - other.amount, self.currency)


@dataclass(frozen=True, slots=True)
class NormalizedTransaction:
    transaction_id: str
    institution: Institution
    account_id: str
    member_id: str | None
    transaction_date: date
    posting_date: date | None
    raw_description: str
    normalized_merchant: str
    merchant_location: str | None
    amount: Money
    transaction_type: TransactionType
    category_id: str | None
    included_in_spend: bool
    reviewed: bool
    fingerprint: str | None = None
    statement_id: str | None = None
    imported_at: datetime | None = None
    source_metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.institution, Institution):
            raise TypeError("institution must be an Institution")
        if not isinstance(self.transaction_type, TransactionType):
            raise TypeError("transaction_type must be a TransactionType")
        if type(self.transaction_date) is not date:
            raise TypeError("transaction_date must be a date")
        if self.posting_date is not None and type(self.posting_date) is not date:
            raise TypeError("posting_date must be a date or None")
        if not isinstance(self.amount, Money):
            raise TypeError("amount must be Money")
        _validate_masked_account_identifier(self.account_id)
        if self.transaction_type in _NEGATIVE_TRANSACTION_TYPES and self.amount.amount >= 0:
            raise ValueError(f"{self.transaction_type.value} amount must be negative")
        if self.transaction_type in _POSITIVE_TRANSACTION_TYPES and self.amount.amount <= 0:
            raise ValueError(f"{self.transaction_type.value} amount must be positive")


@dataclass(frozen=True, slots=True)
class StatementTotal:
    section: str
    amount: Money


@dataclass(frozen=True, slots=True)
class DomainWarning:
    code: str
    message: str
    severity: WarningSeverity
    evidence_ref: str | None = None
    transaction_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.severity, WarningSeverity):
            raise TypeError("severity must be a WarningSeverity")


@dataclass(frozen=True, slots=True)
class NormalizedStatement:
    statement_id: str
    source_name: str
    source_hash: str
    institution: Institution
    account_id: str
    start_date: date
    end_date: date
    closing_date: date
    transactions: tuple[NormalizedTransaction, ...]
    reported_totals: tuple[StatementTotal, ...]
    warnings: tuple[DomainWarning, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.institution, Institution):
            raise TypeError("institution must be an Institution")
        _validate_masked_account_identifier(self.account_id)
        if type(self.start_date) is not date:
            raise TypeError("start_date must be a date")
        if type(self.end_date) is not date:
            raise TypeError("end_date must be a date")
        if type(self.closing_date) is not date:
            raise TypeError("closing_date must be a date")
        if self.end_date < self.start_date:
            raise ValueError("statement date range must end on or after its start date")


@dataclass(frozen=True, slots=True)
class ParseResult:
    statement: NormalizedStatement
    warnings: tuple[DomainWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconciliationLine:
    section: str
    reported: Money
    extracted: Money

    @property
    def difference(self) -> Money:
        return self.extracted - self.reported


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    status: ReconciliationStatus
    lines: tuple[ReconciliationLine, ...]
    override_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ReconciliationStatus):
            raise TypeError("status must be a ReconciliationStatus")
        if self.status is ReconciliationStatus.OVERRIDDEN and not self.override_reason:
            raise ValueError("an overridden reconciliation requires a reason")


@dataclass(frozen=True, slots=True)
class ReviewState:
    statement: NormalizedStatement
    status: ReviewStatus
    reconciliation: ReconciliationResult
    saved_rule_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ReviewStatus):
            raise TypeError("status must be a ReviewStatus")


@dataclass(frozen=True, slots=True)
class MemberConfig:
    member_id: str
    display_name: str
    aliases: tuple[str, ...]
    active: bool


@dataclass(frozen=True, slots=True)
class AccountConfig:
    account_id: str
    institution: Institution
    masked_identifier: str
    default_member_id: str
    display_name: str
    active: bool

    def __post_init__(self) -> None:
        if not isinstance(self.institution, Institution):
            raise TypeError("institution must be an Institution")
        _validate_masked_account_identifier(self.masked_identifier)


@dataclass(frozen=True, slots=True)
class CategoryConfig:
    category_id: str
    display_name: str
    sort_order: int
    active: bool


@dataclass(frozen=True, slots=True)
class MerchantRule:
    rule_id: str
    match_type: MatchType
    match_value: str
    normalized_merchant: str
    category_id: str
    priority: int
    active: bool
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.match_type, MatchType):
            raise TypeError("match_type must be a MatchType")


@dataclass(frozen=True, slots=True)
class WorkbookConfig:
    members: tuple[MemberConfig, ...]
    accounts: tuple[AccountConfig, ...]
    categories: tuple[CategoryConfig, ...]
    merchant_rules: tuple[MerchantRule, ...]

    def __post_init__(self) -> None:
        category_ids = {category.category_id for category in self.categories}
        for rule in self.merchant_rules:
            if rule.category_id not in category_ids:
                raise ValueError(f"merchant rule references unknown category: {rule.category_id}")


@dataclass(frozen=True, slots=True)
class LocalSettings:
    workbook_id: str
    credential_reference: str


@dataclass(frozen=True, slots=True)
class ImportRecord:
    import_id: str
    statement_hash: str
    status: ImportStatus
    transaction_ids: tuple[str, ...]
    imported_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ImportStatus):
            raise TypeError("status must be an ImportStatus")


@dataclass(frozen=True, slots=True)
class ApprovedImport:
    import_id: str
    statement: NormalizedStatement
    reconciliation: ReconciliationResult
    reviewed_at: datetime


@dataclass(frozen=True, slots=True)
class ImportResult:
    import_id: str
    status: ImportStatus
    transaction_ids: tuple[str, ...]
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, ImportStatus):
            raise TypeError("status must be an ImportStatus")


@dataclass(frozen=True, slots=True)
class BackfillCheckpoint:
    root_id: str
    plan_hash: str
    completed_statement_hashes: tuple[str, ...]
    failed_source_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StructuredCacheRecord:
    cache_id: str
    statement_hash: str
    fields: tuple[tuple[str, str], ...]
