"""Single-statement import orchestration, fingerprints, and duplicate handling."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import timedelta
from difflib import SequenceMatcher
from pathlib import Path

from family_spend.domain.models import (
    ApprovedImport,
    DuplicateState,
    ImportStatus,
    NormalizedTransaction,
    ReviewState,
    ReviewStatus,
    StructuredCacheRecord,
    WorkbookConfig,
)
from family_spend.ingestion import StatementIngestionService
from family_spend.ports import Clock, ReviewPort, StructuredCache, WorkbookGateway
from family_spend.review import ReviewEngine, normalize_merchant

_NEAR_DUPLICATE_DAYS = 3
_NEAR_MERCHANT_RATIO = 0.86


def _fingerprint_base(transaction: NormalizedTransaction) -> str:
    effective_date = transaction.posting_date or transaction.transaction_date
    return "\x1f".join(
        (
            transaction.account_id,
            effective_date.isoformat(),
            str(transaction.amount.amount),
            normalize_merchant(transaction.normalized_merchant),
        )
    )


def assign_fingerprints(
    transactions: tuple[NormalizedTransaction, ...],
) -> tuple[NormalizedTransaction, ...]:
    """Assign deterministic fingerprints with a per-base occurrence discriminator."""
    occurrences: dict[str, int] = {}
    fingerprinted: list[NormalizedTransaction] = []
    for transaction in transactions:
        base = _fingerprint_base(transaction)
        occurrence = occurrences.get(base, 0)
        occurrences[base] = occurrence + 1
        digest = hashlib.sha256(f"{base}\x1f{occurrence}".encode()).hexdigest()
        fingerprinted.append(replace(transaction, fingerprint=digest))
    return tuple(fingerprinted)


def _is_near_duplicate(
    transaction: NormalizedTransaction,
    candidate: NormalizedTransaction,
) -> bool:
    if transaction.account_id != candidate.account_id:
        return False
    if transaction.amount != candidate.amount:
        return False
    transaction_date = transaction.posting_date or transaction.transaction_date
    candidate_date = candidate.posting_date or candidate.transaction_date
    if abs((transaction_date - candidate_date).days) > _NEAR_DUPLICATE_DAYS:
        return False
    left = transaction.normalized_merchant
    right = candidate.normalized_merchant
    if min(len(left), len(right)) >= 6 and (left in right or right in left):
        return True
    return SequenceMatcher(None, left, right, autojunk=False).ratio() >= _NEAR_MERCHANT_RATIO


def classify_duplicates(
    transactions: tuple[NormalizedTransaction, ...],
    exact_matches: tuple[NormalizedTransaction, ...],
    near_candidates: tuple[NormalizedTransaction, ...],
) -> dict[str, DuplicateState]:
    """Classify exact fingerprints first and leave similarity decisions for review."""
    exact_fingerprints = {
        transaction.fingerprint
        for transaction in exact_matches
        if transaction.fingerprint is not None
    }
    result: dict[str, DuplicateState] = {}
    for transaction in transactions:
        if transaction.fingerprint in exact_fingerprints:
            result[transaction.transaction_id] = DuplicateState.EXACT
        elif any(_is_near_duplicate(transaction, candidate) for candidate in near_candidates):
            result[transaction.transaction_id] = DuplicateState.NEAR
        else:
            result[transaction.transaction_id] = DuplicateState.NONE
    return result


@dataclass(frozen=True, slots=True)
class SingleImportOutcome:
    """Observable result of one statement import attempt."""

    status: ImportStatus
    message: str
    import_id: str
    imported_count: int
    exact_duplicate_count: int
    cache_id: str | None = None


class SingleImportWorkflow:
    """Compose parsing, review, duplicate checks, cache policy, and commit."""

    def __init__(
        self,
        *,
        ingestion: StatementIngestionService,
        review_engine: ReviewEngine,
        reviewer: ReviewPort,
        workbook: WorkbookGateway,
        configuration: WorkbookConfig,
        cache: StructuredCache,
        clock: Clock,
    ) -> None:
        self._ingestion = ingestion
        self._review_engine = review_engine
        self._reviewer = reviewer
        self._workbook = workbook
        self._configuration = configuration
        self._cache = cache
        self._clock = clock

    def execute(self, source: Path, *, retain_cache: bool = False) -> SingleImportOutcome:
        """Run one PDF through the complete safe import path."""
        results = self._ingestion.parse(source)
        if len(results) != 1:
            raise ValueError("single import accepts exactly one statement PDF")
        parsed = results[0].statement
        import_id = f"import-{parsed.source_hash[:20]}"
        cache_id = f"cache-{parsed.source_hash[:20]}"
        existing = self._workbook.find_import_by_hash(parsed.source_hash)
        if existing is not None and existing.status is ImportStatus.COMPLETE:
            return SingleImportOutcome(
                ImportStatus.SKIPPED,
                "Statement was already imported; workbook state is unchanged.",
                existing.import_id,
                0,
                len(existing.transaction_ids),
            )

        fingerprinted = assign_fingerprints(parsed.transactions)
        fingerprint_values = tuple(
            transaction.fingerprint
            for transaction in fingerprinted
            if transaction.fingerprint is not None
        )
        exact_matches = self._workbook.find_transactions(fingerprint_values)
        near_candidates = self._workbook.transactions_in_window(
            parsed.account_id,
            parsed.start_date - timedelta(days=_NEAR_DUPLICATE_DAYS),
            parsed.end_date + timedelta(days=_NEAR_DUPLICATE_DAYS),
        )
        duplicate_states = classify_duplicates(
            fingerprinted,
            exact_matches,
            near_candidates,
        )
        statement = replace(parsed, transactions=fingerprinted)
        initial = self._review_engine.prepare(
            statement,
            self._configuration,
            duplicates=duplicate_states,
        )
        try:
            self._cache.save(self._cache_record(cache_id, initial, stage="pending_review"))
            decision = self._reviewer.review(initial)
            if decision.statement.statement_id != initial.statement.statement_id:
                raise ValueError("review decision does not belong to the parsed statement")
            self._cache.save(self._cache_record(cache_id, decision, stage="reviewed"))
            if decision.status is ReviewStatus.CANCELLED:
                return SingleImportOutcome(
                    ImportStatus.SKIPPED,
                    "Review cancelled. No transactions or rules were uploaded.",
                    import_id,
                    0,
                    sum(
                        row.duplicate_state is DuplicateState.EXACT for row in decision.rows
                    ),
                    cache_id if retain_cache else None,
                )
            if decision.status is not ReviewStatus.APPROVED:
                raise ValueError("review must explicitly approve or cancel")

            reviewed_at = self._clock.now()
            exact_count = sum(
                row.duplicate_state is DuplicateState.EXACT for row in decision.rows
            )
            imported_transactions = tuple(
                replace(
                    row.current,
                    statement_id=import_id,
                    reviewed=True,
                    imported_at=reviewed_at,
                    source_metadata=(),
                )
                for row in decision.rows
                if row.duplicate_state is not DuplicateState.EXACT
            )
            approved_statement = replace(
                decision.statement,
                transactions=imported_transactions,
            )
            rules = tuple(
                replace(rule, updated_at=reviewed_at) for rule in decision.saved_rules
            )
            approved = ApprovedImport(
                import_id=import_id,
                statement=approved_statement,
                reconciliation=decision.reconciliation,
                reviewed_at=reviewed_at,
                merchant_rules=rules,
            )
            result = self._workbook.commit_import(approved)
            self._cache.save(
                self._cache_record(
                    cache_id,
                    decision,
                    stage=f"commit_{result.status.value}",
                )
            )
            return SingleImportOutcome(
                result.status,
                result.message,
                result.import_id,
                len(result.transaction_ids),
                exact_count,
                cache_id if retain_cache else None,
            )
        finally:
            if not retain_cache:
                self._cache.delete(cache_id)

    @staticmethod
    def _cache_record(
        cache_id: str,
        state: ReviewState,
        *,
        stage: str,
    ) -> StructuredCacheRecord:
        transactions = [
            {
                "transaction_id": row.current.transaction_id,
                "fingerprint": row.current.fingerprint,
                "date": row.current.transaction_date.isoformat(),
                "amount": str(row.current.amount.amount),
                "merchant": row.current.normalized_merchant,
                "member_id": row.current.member_id,
                "category_id": row.current.category_id,
                "type": row.current.transaction_type.value,
                "duplicate_state": row.duplicate_state.value,
                "warning_codes": [warning.code for warning in row.warnings],
            }
            for row in state.rows
        ]
        return StructuredCacheRecord(
            cache_id=cache_id,
            statement_hash=state.statement.source_hash,
            fields=(
                ("stage", stage),
                ("source_name", state.statement.source_name),
                ("review_status", state.status.value),
                ("reconciliation_status", state.reconciliation.status.value),
                ("transactions", json.dumps(transactions, sort_keys=True)),
                (
                    "saved_rule_ids",
                    json.dumps(list(state.saved_rule_ids), sort_keys=True),
                ),
            ),
        )
