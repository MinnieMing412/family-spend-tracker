from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


def _validate_masked_account_identifier(value: str) -> None:
    """Reject account identifiers that expose too many digits or lack masking."""
    if not isinstance(value, str):
        raise TypeError("masked account identifier must be a string")
    digit_count = sum(character.isdigit() for character in value)
    marker_present = any(
        marker in value.lower() for marker in ("ending", "*", "x", "•", "…")
    )
    if not marker_present or not 4 <= digit_count <= 8:
        raise ValueError("account identifier must contain only a masked account identifier")


class Institution(StrEnum):
    """Financial institutions supported by the first product release."""

    AMEX = "amex"
    BANK_OF_AMERICA = "bank_of_america"
    CHASE = "chase"


class TransactionType(StrEnum):
    """Normalized kinds of activity that can appear on a statement."""

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
    """Importance levels for parsing and reconciliation warnings."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class MatchType(StrEnum):
    """Ways a merchant rule can compare its value to transaction text."""

    EXACT = "exact"
    CONTAINS = "contains"


class ReconciliationStatus(StrEnum):
    """Possible outcomes when extracted totals are checked against a statement."""

    MATCHED = "matched"
    DISCREPANCY = "discrepancy"
    OVERRIDDEN = "overridden"
    UNAVAILABLE = "unavailable"


class ReviewStatus(StrEnum):
    """Possible states of a user's statement review."""

    PENDING = "pending"
    APPROVED = "approved"
    CANCELLED = "cancelled"


class ImportStatus(StrEnum):
    """Lifecycle states for a workbook import."""

    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class Money:
    """An exact decimal amount in US dollars.

    `Decimal` avoids the rounding errors associated with floating-point numbers.
    """

    amount: Decimal
    currency: str = "USD"

    def __post_init__(self) -> None:
        """Validate that the amount is finite and the currency is USD."""
        if not isinstance(self.amount, Decimal):
            raise TypeError("money amount must be a Decimal")
        if not self.amount.is_finite():
            raise ValueError("money amount must be finite")
        if self.currency != "USD":
            raise ValueError("v1 supports USD only")

    def __add__(self, other: object) -> Money:
        """Add two monetary values that use the same currency."""
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError("cannot add money in different currencies")
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: object) -> Money:
        """Subtract two monetary values that use the same currency."""
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError("cannot subtract money in different currencies")
        return Money(self.amount - other.amount, self.currency)


@dataclass(frozen=True, slots=True)
class NormalizedTransaction:
    """One bank transaction converted into the application's common format."""

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
        """Validate dates, account masking, type values, and amount direction."""
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
    """A total reported by a named section of the original statement."""

    section: str
    amount: Money


@dataclass(frozen=True, slots=True)
class DomainWarning:
    """A structured warning linked to parsing evidence or a transaction."""

    code: str
    message: str
    severity: WarningSeverity
    evidence_ref: str | None = None
    transaction_id: str | None = None

    def __post_init__(self) -> None:
        """Validate that the warning uses a supported severity."""
        if not isinstance(self.severity, WarningSeverity):
            raise TypeError("severity must be a WarningSeverity")


@dataclass(frozen=True, slots=True)
class NormalizedStatement:
    """A complete statement represented independently of its bank's PDF layout."""

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
        """Validate institution, account masking, and the statement date range."""
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
    """The normalized statement and warnings produced by a statement parser."""

    statement: NormalizedStatement
    warnings: tuple[DomainWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconciliationLine:
    """Comparison between one reported statement total and its extracted total."""

    section: str
    reported: Money
    extracted: Money

    @property
    def difference(self) -> Money:
        """Return extracted minus reported for this reconciliation section."""
        return self.extracted - self.reported


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Overall result of comparing extracted activity with statement totals."""

    status: ReconciliationStatus
    lines: tuple[ReconciliationLine, ...]
    override_reason: str | None = None

    def __post_init__(self) -> None:
        """Validate the status and require an explanation for manual overrides."""
        if not isinstance(self.status, ReconciliationStatus):
            raise TypeError("status must be a ReconciliationStatus")
        if self.status is ReconciliationStatus.OVERRIDDEN and not self.override_reason:
            raise ValueError("an overridden reconciliation requires a reason")


@dataclass(frozen=True, slots=True)
class ReviewState:
    """A statement's reconciliation and current user-review decision."""

    statement: NormalizedStatement
    status: ReviewStatus
    reconciliation: ReconciliationResult
    saved_rule_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate that the review uses a supported status."""
        if not isinstance(self.status, ReviewStatus):
            raise TypeError("status must be a ReviewStatus")


@dataclass(frozen=True, slots=True)
class MemberConfig:
    """A family member available for transaction ownership assignment."""

    member_id: str
    display_name: str
    aliases: tuple[str, ...]
    active: bool


@dataclass(frozen=True, slots=True)
class AccountConfig:
    """A configured financial account assigned to a default family member."""

    account_id: str
    institution: Institution
    masked_identifier: str
    default_member_id: str
    display_name: str
    active: bool

    def __post_init__(self) -> None:
        """Validate the institution and ensure the displayed account is masked."""
        if not isinstance(self.institution, Institution):
            raise TypeError("institution must be an Institution")
        _validate_masked_account_identifier(self.masked_identifier)


@dataclass(frozen=True, slots=True)
class CategoryConfig:
    """A spending category displayed in review tools and analysis charts."""

    category_id: str
    display_name: str
    sort_order: int
    active: bool


@dataclass(frozen=True, slots=True)
class MerchantRule:
    """A reusable rule that normalizes and categorizes matching merchants."""

    rule_id: str
    match_type: MatchType
    match_value: str
    normalized_merchant: str
    category_id: str
    priority: int
    active: bool
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate that the rule uses a supported matching strategy."""
        if not isinstance(self.match_type, MatchType):
            raise TypeError("match_type must be a MatchType")


@dataclass(frozen=True, slots=True)
class WorkbookConfig:
    """All user-editable configuration loaded from the Google workbook."""

    members: tuple[MemberConfig, ...]
    accounts: tuple[AccountConfig, ...]
    categories: tuple[CategoryConfig, ...]
    merchant_rules: tuple[MerchantRule, ...]

    def __post_init__(self) -> None:
        """Reject merchant rules that reference categories that do not exist."""
        category_ids = {category.category_id for category in self.categories}
        for rule in self.merchant_rules:
            if rule.category_id not in category_ids:
                raise ValueError(f"merchant rule references unknown category: {rule.category_id}")


@dataclass(frozen=True, slots=True)
class LocalSettings:
    """Local references needed to reconnect to a Google Sheets workbook."""

    workbook_id: str
    credential_reference: str


@dataclass(frozen=True, slots=True)
class ImportRecord:
    """Audit record for a statement import already written to the workbook."""

    import_id: str
    statement_hash: str
    status: ImportStatus
    transaction_ids: tuple[str, ...]
    imported_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate that the import uses a supported status."""
        if not isinstance(self.status, ImportStatus):
            raise TypeError("status must be an ImportStatus")


@dataclass(frozen=True, slots=True)
class ApprovedImport:
    """A reviewed and reconciled statement ready for atomic workbook storage."""

    import_id: str
    statement: NormalizedStatement
    reconciliation: ReconciliationResult
    reviewed_at: datetime


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Outcome returned after attempting to commit a statement import."""

    import_id: str
    status: ImportStatus
    transaction_ids: tuple[str, ...]
    message: str

    def __post_init__(self) -> None:
        """Validate that the result uses a supported import status."""
        if not isinstance(self.status, ImportStatus):
            raise TypeError("status must be an ImportStatus")


@dataclass(frozen=True, slots=True)
class BackfillCheckpoint:
    """Saved progress for a resumable historical statement backfill."""

    root_id: str
    plan_hash: str
    completed_statement_hashes: tuple[str, ...]
    failed_source_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StructuredCacheRecord:
    """Structured parser data that can be retained without storing raw PDF text."""

    cache_id: str
    statement_hash: str
    fields: tuple[tuple[str, str], ...]
