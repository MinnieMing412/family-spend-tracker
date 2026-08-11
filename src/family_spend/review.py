"""Pure enrichment, reconciliation, and review-state transformations."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation

from family_spend.domain.models import (
    CategorizationSource,
    DomainWarning,
    DuplicateState,
    MatchType,
    MemberConfig,
    MerchantRule,
    Money,
    NormalizedStatement,
    NormalizedTransaction,
    ReconciliationLine,
    ReconciliationResult,
    ReconciliationStatus,
    ReviewRow,
    ReviewState,
    ReviewStatus,
    TransactionType,
    WarningSeverity,
    WorkbookConfig,
)

RECONCILIATION_TOLERANCE = Decimal("0.01")
_SPEND_TYPES = frozenset(
    {
        TransactionType.PURCHASE,
        TransactionType.MERCHANT_CREDIT,
        TransactionType.FEE,
        TransactionType.INTEREST,
        TransactionType.CASH_ADVANCE,
        TransactionType.OTHER,
    }
)
_NOISE_PREFIX = re.compile(r"^(?:SQ|TST|SP)\s*[*-]\s*", re.IGNORECASE)
_TRAILING_REFERENCE = re.compile(r"(?:\s+#?\d{4,}|\s+REF\s+[A-Z0-9-]+)$", re.IGNORECASE)


def normalize_merchant(value: str) -> str:
    """Normalize merchant text independently from category selection."""
    decomposed = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    normalized = normalized.upper().strip()
    normalized = _NOISE_PREFIX.sub("", normalized)
    normalized = _TRAILING_REFERENCE.sub("", normalized)
    normalized = re.sub(r"[^A-Z0-9&]+", " ", normalized)
    return " ".join(normalized.split())


def included_in_spend(transaction_type: TransactionType) -> bool:
    """Derive analytical inclusion from transaction type, never category."""
    return transaction_type in _SPEND_TYPES


def _normalized_member_values(member: MemberConfig) -> frozenset[str]:
    return frozenset(
        normalize_merchant(value)
        for value in (member.display_name, *member.aliases)
        if value.strip()
    )


def _ownership(
    transaction: NormalizedTransaction,
    configuration: WorkbookConfig,
) -> tuple[str | None, tuple[DomainWarning, ...]]:
    if transaction.member_id is not None:
        return transaction.member_id, ()

    metadata = dict(transaction.source_metadata)
    cardholder = metadata.get("cardholder")
    active_members = tuple(member for member in configuration.members if member.active)
    if cardholder:
        normalized_cardholder = normalize_merchant(cardholder)
        matches = tuple(
            member
            for member in active_members
            if normalized_cardholder in _normalized_member_values(member)
        )
        if len(matches) == 1:
            return matches[0].member_id, ()
        if len(matches) > 1:
            return None, (
                DomainWarning(
                    code="ownership-ambiguous-alias",
                    message="Cardholder alias matches multiple active members.",
                    severity=WarningSeverity.WARNING,
                    transaction_id=transaction.transaction_id,
                ),
            )

    accounts = tuple(
        account
        for account in configuration.accounts
        if account.active
        and transaction.account_id in {account.account_id, account.masked_identifier}
    )
    if len(accounts) == 1:
        default_member_id = accounts[0].default_member_id
        if any(member.member_id == default_member_id for member in active_members):
            return default_member_id, ()
        return None, (
            DomainWarning(
                code="ownership-inactive-account-default",
                message="Configured account owner is not an active member.",
                severity=WarningSeverity.WARNING,
                transaction_id=transaction.transaction_id,
            ),
        )
    code = "ownership-ambiguous-account" if len(accounts) > 1 else "ownership-unresolved"
    message = (
        "Masked account matches multiple active accounts."
        if len(accounts) > 1
        else "Transaction owner could not be resolved from aliases or account defaults."
    )
    return None, (
        DomainWarning(
            code=code,
            message=message,
            severity=WarningSeverity.WARNING,
            transaction_id=transaction.transaction_id,
        ),
    )


def _matching_rule(
    merchant: str,
    rules: tuple[MerchantRule, ...],
) -> tuple[MerchantRule | None, CategorizationSource]:
    active = tuple(rule for rule in rules if rule.active)
    exact = sorted(
        (rule for rule in active if rule.match_type is MatchType.EXACT),
        key=lambda rule: (-rule.priority, rule.rule_id),
    )
    contains = sorted(
        (rule for rule in active if rule.match_type is MatchType.CONTAINS),
        key=lambda rule: (-rule.priority, rule.rule_id),
    )
    for rule in exact:
        if merchant == normalize_merchant(rule.match_value):
            return rule, CategorizationSource.EXACT_RULE
    for rule in contains:
        if normalize_merchant(rule.match_value) in merchant:
            return rule, CategorizationSource.CONTAINS_RULE
    return None, CategorizationSource.UNCATEGORIZED


def enrich_transaction(
    transaction: NormalizedTransaction,
    configuration: WorkbookConfig,
    *,
    duplicate_state: DuplicateState = DuplicateState.NONE,
) -> ReviewRow:
    """Resolve ownership, merchant, category, spend inclusion, and warnings."""
    member_id, owner_warnings = _ownership(transaction, configuration)
    merchant = normalize_merchant(transaction.normalized_merchant or transaction.raw_description)
    spend = included_in_spend(transaction.transaction_type)
    rule, category_source = _matching_rule(merchant, configuration.merchant_rules)
    warnings = list(owner_warnings)
    if not spend:
        category_id = None
        category_source = CategorizationSource.NOT_APPLICABLE
    elif rule is not None and any(
        category.active and category.category_id == rule.category_id
        for category in configuration.categories
    ):
        merchant = normalize_merchant(rule.normalized_merchant)
        category_id = rule.category_id
    else:
        category_id = "uncategorized"
        category_source = CategorizationSource.UNCATEGORIZED
        warnings.append(
            DomainWarning(
                code="category-uncategorized",
                message="Spending transaction has no matching merchant rule.",
                severity=WarningSeverity.WARNING,
                transaction_id=transaction.transaction_id,
            )
        )
    if duplicate_state is DuplicateState.NEAR:
        warnings.append(
            DomainWarning(
                code="near-duplicate",
                message="Transaction resembles an existing row and requires review.",
                severity=WarningSeverity.WARNING,
                transaction_id=transaction.transaction_id,
            )
        )
    elif duplicate_state is DuplicateState.EXACT:
        warnings.append(
            DomainWarning(
                code="exact-duplicate",
                message="Transaction exactly matches an existing row.",
                severity=WarningSeverity.INFO,
                transaction_id=transaction.transaction_id,
            )
        )
    current = replace(
        transaction,
        member_id=member_id,
        normalized_merchant=merchant,
        category_id=category_id,
        included_in_spend=spend,
    )
    return ReviewRow(
        original=transaction,
        current=current,
        warnings=tuple(warnings),
        duplicate_state=duplicate_state,
        categorization_source=category_source,
    )


def _types_for_section(section: str) -> frozenset[TransactionType] | None:
    normalized = "_".join(section.casefold().replace("&", "and").split())
    if normalized.startswith("payments"):
        return frozenset({TransactionType.PAYMENT})
    if normalized.startswith("credits"):
        return frozenset({TransactionType.MERCHANT_CREDIT})
    if normalized.startswith("new_charges"):
        return frozenset(
            {
                TransactionType.PURCHASE,
                TransactionType.CASH_ADVANCE,
                TransactionType.OTHER,
            }
        )
    if normalized.startswith("fees"):
        return frozenset({TransactionType.FEE})
    if normalized.startswith("interest"):
        return frozenset({TransactionType.INTEREST})
    return None


def _cardholder_for_section(section: str) -> str | None:
    normalized = "_".join(section.casefold().split())
    prefix = "new_charges_for_"
    if not normalized.startswith(prefix):
        return None
    return normalize_merchant(normalized.removeprefix(prefix).replace("_", " "))


def reconcile_statement(statement: NormalizedStatement) -> ReconciliationResult:
    """Reconcile each supported reported section with exact decimal sums."""
    lines: list[ReconciliationLine] = []
    for total in statement.reported_totals:
        transaction_types = _types_for_section(total.section)
        if transaction_types is None:
            continue
        cardholder = _cardholder_for_section(total.section)
        extracted = sum(
            (
                transaction.amount.amount
                for transaction in statement.transactions
                if transaction.transaction_type in transaction_types
                and (
                    cardholder is None
                    or normalize_merchant(
                        dict(transaction.source_metadata).get("cardholder", "")
                    )
                    == cardholder
                )
            ),
            Decimal("0"),
        )
        lines.append(
            ReconciliationLine(
                section=total.section,
                reported=total.amount,
                extracted=Money(extracted),
            )
        )
    if not lines:
        return ReconciliationResult(ReconciliationStatus.UNAVAILABLE, ())
    status = (
        ReconciliationStatus.MATCHED
        if all(abs(line.difference.amount) <= RECONCILIATION_TOLERANCE for line in lines)
        else ReconciliationStatus.DISCREPANCY
    )
    return ReconciliationResult(status, tuple(lines))


class ReviewEngine:
    """Build and update review snapshots using authoritative workbook configuration."""

    def prepare(
        self,
        statement: NormalizedStatement,
        configuration: WorkbookConfig,
        *,
        duplicates: Mapping[str, DuplicateState] | None = None,
    ) -> ReviewState:
        """Enrich parsed rows and compute their initial reconciliation and cleanliness."""
        duplicate_values = duplicates or {}
        rows = tuple(
            enrich_transaction(
                transaction,
                configuration,
                duplicate_state=duplicate_values.get(
                    transaction.transaction_id,
                    DuplicateState.NONE,
                ),
            )
            for transaction in statement.transactions
        )
        current_statement = replace(
            statement,
            transactions=tuple(row.current for row in rows),
        )
        return ReviewState(
            statement=current_statement,
            status=ReviewStatus.PENDING,
            reconciliation=reconcile_statement(current_statement),
            rows=rows,
            valid_member_ids=tuple(
                member.member_id for member in configuration.members if member.active
            ),
            valid_category_ids=tuple(
                category.category_id
                for category in configuration.categories
                if category.active
            ),
        )

    def decide(
        self,
        state: ReviewState,
        *,
        status: ReviewStatus,
        rows: tuple[ReviewRow, ...] | None = None,
        saved_rules: tuple[MerchantRule, ...] | None = None,
        override_reason: str | None = None,
    ) -> ReviewState:
        """Apply corrected rows and an explicit approve or cancel decision."""
        current_rows = rows if rows is not None else state.rows
        statement = replace(
            state.statement,
            transactions=tuple(row.current for row in current_rows),
        )
        reconciliation = reconcile_statement(statement)
        if override_reason is not None:
            if not override_reason.strip():
                raise ValueError("reconciliation override requires a non-empty reason")
            if reconciliation.status is not ReconciliationStatus.DISCREPANCY:
                raise ValueError("only a reconciliation discrepancy can be overridden")
            reconciliation = ReconciliationResult(
                ReconciliationStatus.OVERRIDDEN,
                reconciliation.lines,
                override_reason.strip(),
            )
        rules = saved_rules if saved_rules is not None else state.saved_rules
        return ReviewState(
            statement=statement,
            status=status,
            reconciliation=reconciliation,
            saved_rule_ids=tuple(rule.rule_id for rule in rules),
            rows=current_rows,
            saved_rules=rules,
            valid_member_ids=state.valid_member_ids,
            valid_category_ids=state.valid_category_ids,
        )


def edit_review_row(row: ReviewRow, field: str, value: str) -> ReviewRow:
    """Apply one explicit terminal correction while preserving row identity."""
    current = row.current
    source = row.categorization_source
    normalized_field = field.casefold().replace("-", "_")
    if normalized_field == "member":
        current = replace(current, member_id=None if value.casefold() == "none" else value)
    elif normalized_field == "merchant":
        current = replace(current, normalized_merchant=normalize_merchant(value))
    elif normalized_field == "date":
        current = replace(current, transaction_date=date.fromisoformat(value))
    elif normalized_field == "amount":
        try:
            amount = Decimal(value.replace(",", "").replace("$", ""))
        except InvalidOperation as error:
            raise ValueError("amount must be an exact decimal") from error
        if current.transaction_type in {TransactionType.PAYMENT, TransactionType.MERCHANT_CREDIT}:
            amount = -abs(amount)
        elif current.transaction_type in _SPEND_TYPES:
            amount = abs(amount)
        current = replace(current, amount=Money(amount))
    elif normalized_field == "type":
        transaction_type = TransactionType(value.casefold())
        amount = current.amount.amount
        if transaction_type in {TransactionType.PAYMENT, TransactionType.MERCHANT_CREDIT}:
            amount = -abs(amount)
        elif transaction_type in _SPEND_TYPES:
            amount = abs(amount)
        current = replace(
            current,
            transaction_type=transaction_type,
            amount=Money(amount),
            included_in_spend=included_in_spend(transaction_type),
            category_id=(
                current.category_id if included_in_spend(transaction_type) else None
            ),
        )
    elif normalized_field == "category":
        current = replace(current, category_id=value)
        source = CategorizationSource.MANUAL
    else:
        raise ValueError(f"unsupported review field: {field}")

    resolved_codes: set[str] = set()
    if current.member_id is not None:
        resolved_codes.update(
            {"ownership-unresolved", "ownership-ambiguous-alias", "ownership-ambiguous-account"}
        )
    if (current.category_id or "").casefold() != "uncategorized":
        resolved_codes.add("category-uncategorized")
    warnings = tuple(warning for warning in row.warnings if warning.code not in resolved_codes)
    return replace(
        row,
        current=current,
        warnings=warnings,
        categorization_source=source,
    )


def save_rule_for_row(row: ReviewRow, match_type: MatchType) -> MerchantRule:
    """Create a deterministic approved merchant rule from a corrected row."""
    merchant = row.current.normalized_merchant
    category_id = row.current.category_id
    if not merchant or not category_id or category_id.casefold() == "uncategorized":
        raise ValueError("saving a rule requires a merchant and resolved category")
    stable_value = f"{row.current.transaction_id}:{match_type.value}:{merchant}:{category_id}"
    return MerchantRule(
        rule_id=f"rule-{hashlib.sha256(stable_value.encode()).hexdigest()[:16]}",
        match_type=match_type,
        match_value=merchant,
        normalized_merchant=merchant,
        category_id=category_id,
        priority=100,
        active=True,
    )


def resolve_near_duplicate(row: ReviewRow) -> ReviewRow:
    """Record an explicit decision that a near-duplicate row is legitimate."""
    if row.duplicate_state is not DuplicateState.NEAR:
        raise ValueError("row is not marked as a near-duplicate")
    return replace(
        row,
        duplicate_state=DuplicateState.NONE,
        warnings=tuple(warning for warning in row.warnings if warning.code != "near-duplicate"),
    )
