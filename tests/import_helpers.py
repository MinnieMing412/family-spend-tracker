"""Reusable deterministic boundaries for Phase 4 import acceptance tests."""

from __future__ import annotations

from pathlib import Path

from family_spend.domain.models import (
    AccountConfig,
    CategoryConfig,
    DuplicateState,
    Institution,
    MatchType,
    MemberConfig,
    MerchantRule,
    ReviewState,
    ReviewStatus,
    WorkbookConfig,
)
from family_spend.ingestion import (
    MarkerParserRegistry,
    ParserRegistration,
    PdfValidator,
    StatementIngestionService,
)
from family_spend.parsers import AmexStatementParser
from family_spend.review import (
    ReviewEngine,
    edit_review_row,
    resolve_near_duplicate,
    save_rule_for_row,
)
from tests.pdf_factory import write_text_pdf

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "amex" / "synthetic_statement.txt"


def build_ingestion() -> StatementIngestionService:
    parser = AmexStatementParser()
    return StatementIngestionService(
        PdfValidator(),
        MarkerParserRegistry(
            (
                ParserRegistration(
                    Institution.AMEX,
                    ("American Express", "Account Ending", "New Charges"),
                    parser,
                ),
            )
        ),
    )


def workbook_configuration() -> WorkbookConfig:
    return WorkbookConfig(
        members=(
            MemberConfig("member-alpha", "Alpha", ("MEMBER ALPHA",), True),
            MemberConfig("member-beta", "Beta", ("MEMBER BETA",), True),
        ),
        accounts=(
            AccountConfig(
                "amex-primary",
                Institution.AMEX,
                "ending-10005",
                "member-alpha",
                "AMEX",
                True,
            ),
        ),
        categories=(
            CategoryConfig("uncategorized", "Uncategorized", 1, True),
            CategoryConfig("other", "Other", 2, True),
        ),
        merchant_rules=(),
    )


def write_statement(path: Path, *, replace_text: tuple[str, str] | None = None) -> None:
    text = FIXTURE.read_text()
    if replace_text is not None:
        text = text.replace(*replace_text)
    write_text_pdf(path, tuple(text.split("\f")))


class ApprovingReviewer:
    """Resolve expected fixture exceptions and explicitly approve."""

    def __init__(
        self,
        engine: ReviewEngine,
        *,
        save_rule: bool = False,
        resolve_near: bool = True,
    ) -> None:
        self._engine = engine
        self._save_rule = save_rule
        self._resolve_near = resolve_near
        self.call_count = 0
        self.seen_duplicate_states: list[tuple[DuplicateState, ...]] = []

    def review(self, state: ReviewState) -> ReviewState:
        self.call_count += 1
        self.seen_duplicate_states.append(
            tuple(row.duplicate_state for row in state.rows)
        )
        rows = []
        for row in state.rows:
            corrected = row
            if corrected.current.included_in_spend and (
                corrected.current.category_id or ""
            ).casefold() == "uncategorized":
                corrected = edit_review_row(corrected, "category", "other")
            if corrected.duplicate_state is DuplicateState.NEAR and self._resolve_near:
                corrected = resolve_near_duplicate(corrected)
            rows.append(corrected)
        rules: tuple[MerchantRule, ...] = ()
        if self._save_rule:
            row = next(item for item in rows if item.current.included_in_spend)
            rules = (save_rule_for_row(row, MatchType.EXACT),)
        return self._engine.decide(
            state,
            status=ReviewStatus.APPROVED,
            rows=tuple(rows),
            saved_rules=rules,
        )


class CancellingReviewer:
    def __init__(self, engine: ReviewEngine) -> None:
        self._engine = engine

    def review(self, state: ReviewState) -> ReviewState:
        return self._engine.decide(state, status=ReviewStatus.CANCELLED)
