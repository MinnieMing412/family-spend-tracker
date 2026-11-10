"""Accessible line-oriented terminal review table."""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import TextIO

from family_spend.domain.models import (
    CategorizationSource,
    MatchType,
    MerchantRule,
    ReconciliationStatus,
    ReviewRow,
    ReviewState,
    ReviewStatus,
    WarningSeverity,
)
from family_spend.review import (
    ReviewEngine,
    edit_review_row,
    normalize_merchant,
    resolve_near_duplicate,
    save_rule_for_row,
)


class TerminalReviewPort:
    """Review transactions through a table and explicit text commands."""

    def __init__(
        self,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
        engine: ReviewEngine | None = None,
    ) -> None:
        self._input = input_stream or sys.stdin
        self._output = output_stream or sys.stdout
        self._engine = engine or ReviewEngine()

    def review(self, state: ReviewState) -> ReviewState:
        """Collect corrections until the user explicitly approves or cancels."""
        current = state
        filter_mode = "all"
        override_reason: str | None = None
        while True:
            self._render(current, filter_mode=filter_mode)
            self._output.write("review> ")
            self._output.flush()
            command_line = self._input.readline()
            if command_line == "":
                return self._engine.decide(current, status=ReviewStatus.CANCELLED)
            parts = command_line.strip().split()
            if not parts:
                continue
            command = parts[0].casefold()
            try:
                if command == "cancel":
                    return self._engine.decide(current, status=ReviewStatus.CANCELLED)
                if command == "approve":
                    if not current.is_clean:
                        raise ValueError(self._approval_blockers(current))
                    return self._engine.decide(
                        current,
                        status=ReviewStatus.APPROVED,
                        override_reason=override_reason,
                    )
                if command == "filter" and len(parts) == 2:
                    if parts[1] not in {"all", "exceptions", "unsaved"}:
                        raise ValueError("filter must be all, exceptions, or unsaved")
                    filter_mode = parts[1]
                    continue
                if command == "edit" and len(parts) >= 4:
                    index = self._row_index(parts[1], current.rows)
                    value = " ".join(parts[3:])
                    self._validate_reference(parts[2], value, current)
                    rows = list(current.rows)
                    rows[index] = edit_review_row(
                        rows[index],
                        parts[2],
                        value,
                    )
                    current = self._engine.decide(
                        current,
                        status=ReviewStatus.PENDING,
                        rows=tuple(rows),
                        override_reason=override_reason,
                    )
                    continue
                if command == "bulk-merchant" and len(parts) >= 3:
                    merchant_values, row_values = self._bulk_arguments(
                        parts[1:],
                        value_name="merchant",
                    )
                    merchant = " ".join(merchant_values).strip()
                    if not merchant:
                        raise ValueError("bulk merchant must not be empty")
                    indexes = self._bulk_indexes(row_values, current)
                    rows = list(current.rows)
                    for index in indexes:
                        rows[index] = edit_review_row(rows[index], "merchant", merchant)
                    current = self._engine.decide(
                        current,
                        status=ReviewStatus.PENDING,
                        rows=tuple(rows),
                        override_reason=override_reason,
                    )
                    continue
                if command == "bulk-category" and len(parts) >= 3:
                    category = parts[1]
                    self._validate_reference("category", category, current)
                    rows = list(current.rows)
                    indexes = self._bulk_indexes(parts[2:], current)
                    for index in indexes:
                        rows[index] = edit_review_row(rows[index], "category", category)
                    current = self._engine.decide(
                        current,
                        status=ReviewStatus.PENDING,
                        rows=tuple(rows),
                        override_reason=override_reason,
                    )
                    continue
                if command == "save-rules" and len(parts) >= 3:
                    match_type = MatchType(parts[1].casefold())
                    selectors = parts[2:]
                    if len(selectors) == 1 and selectors[0].casefold() == "unsaved":
                        selected_indexes = tuple(
                            index
                            for index, row in enumerate(current.rows)
                            if self._is_rule_eligible(row)
                            and not self._has_saved_rule(row, current.saved_rules)
                        )
                    else:
                        selected_indexes = tuple(
                            self._row_index(value, current.rows) for value in selectors
                        )
                    selected_rules = tuple(
                        save_rule_for_row(current.rows[index], match_type)
                        for index in selected_indexes
                    )
                    rules_by_behavior = {
                        self._rule_behavior(rule): rule for rule in current.saved_rules
                    }
                    for rule in selected_rules:
                        rules_by_behavior.setdefault(self._rule_behavior(rule), rule)
                    rules = tuple(rules_by_behavior.values())
                    current = replace(
                        current,
                        saved_rule_ids=tuple(rule.rule_id for rule in rules),
                        saved_rules=rules,
                    )
                    continue
                if command == "resolve-duplicate" and len(parts) == 2:
                    index = self._row_index(parts[1], current.rows)
                    rows = list(current.rows)
                    rows[index] = resolve_near_duplicate(rows[index])
                    current = self._engine.decide(
                        current,
                        status=ReviewStatus.PENDING,
                        rows=tuple(rows),
                        override_reason=override_reason,
                    )
                    continue
                if command == "acknowledge-warning" and len(parts) == 2:
                    code = parts[1]
                    blocking_codes = {
                        warning.code
                        for warning in current.statement.warnings
                        if warning.severity in {
                            WarningSeverity.WARNING,
                            WarningSeverity.ERROR,
                        }
                    }
                    if code not in blocking_codes:
                        raise ValueError("warning code is not a blocking statement warning")
                    current = replace(
                        current,
                        acknowledged_warning_codes=tuple(
                            dict.fromkeys((*current.acknowledged_warning_codes, code))
                        ),
                    )
                    continue
                if command == "override" and len(parts) >= 2:
                    override_reason = (
                        None
                        if len(parts) == 2 and parts[1].casefold() == "clear"
                        else " ".join(parts[1:]).strip()
                    )
                    current = self._engine.decide(
                        current,
                        status=ReviewStatus.PENDING,
                        override_reason=override_reason,
                    )
                    continue
                if command == "help":
                    continue
                raise ValueError("unknown or incomplete review command")
            except (ValueError, IndexError) as error:
                self._write(f"Error: {error}")

    def _render(self, state: ReviewState, *, filter_mode: str) -> None:
        self._write("")
        self._write(
            "# | Date       | Member       | Merchant             | "
            "Amount      | Category       | Rule Saved | Flags"
        )
        self._write(
            "--+------------+--------------+----------------------+"
            "-------------+----------------+------------+----------------"
        )
        displayed = 0
        for index, row in enumerate(state.rows, start=1):
            rule_saved = self._has_saved_rule(row, state.saved_rules)
            if filter_mode == "exceptions" and not row.is_exception:
                continue
            if filter_mode == "unsaved" and (
                not self._is_rule_eligible(row) or rule_saved
            ):
                continue
            displayed += 1
            transaction = row.current
            flags = self._flags(row)
            rule_saved_text = "YES" if rule_saved else "NO"
            self._write(
                f"{index:<2}| {transaction.transaction_date.isoformat():<11}| "
                f"{(transaction.member_id or 'UNRESOLVED')[:12]:<13}| "
                f"{transaction.normalized_merchant[:20]:<21}| "
                f"{transaction.amount.amount!s:>11} | "
                f"{(transaction.category_id or 'N/A')[:14]:<15}| "
                f"{rule_saved_text:<11}| {flags}"
            )
        if displayed == 0:
            self._write("No rows match the current filter.")
        blocking_statement_warnings = tuple(
            warning
            for warning in state.statement.warnings
            if warning.severity in {WarningSeverity.WARNING, WarningSeverity.ERROR}
        )
        if blocking_statement_warnings:
            source = state.source_path or state.statement.source_name
            self._write(f"Statement warnings for {source}:")
            for warning in blocking_statement_warnings:
                status = (
                    "ACKNOWLEDGED"
                    if warning.code in state.acknowledged_warning_codes
                    else "BLOCKING"
                )
                evidence = f" ({warning.evidence_ref})" if warning.evidence_ref else ""
                self._write(
                    f"  {warning.code} [{status}]: {warning.message}{evidence}"
                )
        self._write(
            f"Reconciliation: {state.reconciliation.status.value}; "
            f"clean: {'yes' if state.is_clean else 'no'}; "
            f"saved rules: {len(state.saved_rules)}"
        )
        self._help()

    @staticmethod
    def _flags(row: ReviewRow) -> str:
        flags: list[str] = []
        if not row.current.member_id:
            flags.append("OWNER")
        if row.current.included_in_spend and (
            not row.current.category_id
            or row.current.category_id.casefold() == "uncategorized"
        ):
            flags.append("CATEGORY")
        if row.duplicate_state.value == "near":
            flags.append("NEAR-DUP")
        flags.extend(warning.code.upper() for warning in row.warnings)
        return ",".join(dict.fromkeys(flags)) or "OK"

    @staticmethod
    def _has_saved_rule(
        row: ReviewRow,
        newly_saved_rules: tuple[MerchantRule, ...],
    ) -> bool:
        """Return whether a persisted or pending rule supports the row's category."""
        if row.categorization_source in {
            CategorizationSource.EXACT_RULE,
            CategorizationSource.CONTAINS_RULE,
        }:
            return True
        merchant = normalize_merchant(row.current.normalized_merchant)
        category_id = row.current.category_id
        for rule in newly_saved_rules:
            if not rule.active or rule.category_id != category_id:
                continue
            match_value = normalize_merchant(rule.match_value)
            if rule.match_type is MatchType.EXACT and merchant == match_value:
                return True
            if rule.match_type is MatchType.CONTAINS and match_value in merchant:
                return True
        return False

    @staticmethod
    def _is_rule_eligible(row: ReviewRow) -> bool:
        """Return whether the row has enough resolved spend data to save a rule."""
        category_id = row.current.category_id
        return bool(
            row.current.included_in_spend
            and row.current.normalized_merchant
            and category_id
            and category_id.casefold() != "uncategorized"
        )

    @staticmethod
    def _rule_behavior(rule: MerchantRule) -> tuple[MatchType, str, str, str]:
        """Identify semantically equivalent rules independently of their stable IDs."""
        return (
            rule.match_type,
            normalize_merchant(rule.match_value),
            normalize_merchant(rule.normalized_merchant),
            rule.category_id,
        )

    @staticmethod
    def _approval_blockers(state: ReviewState) -> str:
        """Describe every visible action still required before approval."""
        blockers: list[str] = []
        exception_rows = tuple(
            str(index)
            for index, row in enumerate(state.rows, start=1)
            if row.is_exception
        )
        if exception_rows:
            blockers.append(f"resolve row(s) {', '.join(exception_rows)}")
        invalid_reference_rows = tuple(
            str(index)
            for index, row in enumerate(state.rows, start=1)
            if (
                state.valid_member_ids
                and row.current.member_id not in state.valid_member_ids
            )
            or (
                row.current.included_in_spend
                and state.valid_category_ids
                and row.current.category_id not in state.valid_category_ids
            )
        )
        if invalid_reference_rows:
            blockers.append(
                f"correct workbook references on row(s) {', '.join(invalid_reference_rows)}"
            )
        warning_codes = tuple(
            warning.code
            for warning in state.statement.warnings
            if warning.severity in {WarningSeverity.WARNING, WarningSeverity.ERROR}
            and warning.code not in state.acknowledged_warning_codes
        )
        if warning_codes:
            source = state.source_path or state.statement.source_name
            blockers.append(
                "acknowledge statement warning(s) "
                + ", ".join(dict.fromkeys(warning_codes))
                + f" in {source}"
            )
        if state.reconciliation.status not in {
            ReconciliationStatus.MATCHED,
            ReconciliationStatus.OVERRIDDEN,
        }:
            blockers.append(f"resolve reconciliation {state.reconciliation.status.value}")
        return "approval blocked; " + "; ".join(blockers)

    @staticmethod
    def _row_index(value: str, rows: tuple[ReviewRow, ...]) -> int:
        index = int(value) - 1
        if index < 0 or index >= len(rows):
            raise IndexError("row index is out of range")
        return index

    @staticmethod
    def _bulk_arguments(
        values: list[str],
        *,
        value_name: str,
    ) -> tuple[list[str], list[str]]:
        """Split a possibly multi-word value from explicit rows or a match selector."""
        if "--same-as" in values:
            marker = values.index("--same-as")
            value_parts = values[:marker]
            row_values = values[marker:]
            if not value_parts or len(row_values) != 2:
                raise ValueError(
                    f"bulk-{value_name} requires {value_name.upper()} --same-as ROW"
                )
            return value_parts, row_values
        row_start = len(values)
        while row_start > 0 and values[row_start - 1].isdecimal():
            row_start -= 1
        value_parts = values[:row_start]
        row_values = values[row_start:]
        if not row_values or not value_parts:
            raise ValueError(
                f"bulk-{value_name} requires {value_name.upper()} followed by ROW [ROW ...]"
            )
        return value_parts, row_values

    def _bulk_indexes(self, values: list[str], state: ReviewState) -> set[int]:
        """Resolve explicit row numbers or every exact merchant match to one row."""
        if values[0] == "--same-as":
            reference_index = self._row_index(values[1], state.rows)
            reference_merchant = state.rows[
                reference_index
            ].current.normalized_merchant
            return {
                index
                for index, row in enumerate(state.rows)
                if row.current.normalized_merchant == reference_merchant
            }
        return {self._row_index(value, state.rows) for value in values}

    @staticmethod
    def _validate_reference(field: str, value: str, state: ReviewState) -> None:
        normalized_field = field.casefold().replace("-", "_")
        if (
            normalized_field == "member"
            and value.casefold() != "none"
            and state.valid_member_ids
            and value not in state.valid_member_ids
        ):
            raise ValueError("member must be an active workbook member ID")
        if (
            normalized_field == "category"
            and state.valid_category_ids
            and value not in state.valid_category_ids
        ):
            raise ValueError("category must be an active workbook category ID")

    def _help(self) -> None:
        self._write("Commands:")
        self._write("  edit ROW member|merchant|date|amount|type|category VALUE")
        self._write("  bulk-merchant MERCHANT ROW [ROW ...] | MERCHANT --same-as ROW")
        self._write("  bulk-category CATEGORY ROW [ROW ...] | CATEGORY --same-as ROW")
        self._write(
            "  save-rules exact|contains ROW [ROW ...]|unsaved  (future imports)"
        )
        self._write("  resolve-duplicate ROW")
        self._write("  acknowledge-warning CODE  (after checking the PDF)")
        self._write("  override NON-EMPTY REASON; override clear")
        self._write("  filter all|exceptions|unsaved; approve; cancel; help")

    def _write(self, value: str) -> None:
        self._output.write(value + "\n")


class TerminalBackfillReviewPort:
    """Present backfill scope and bulk decisions without exposing transaction text."""

    def __init__(
        self,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ) -> None:
        self._input = input_stream or sys.stdin
        self._output = output_stream or sys.stdout

    def confirm_plan(self, relative_paths: tuple[str, ...]) -> bool:
        self._write(f"Discovered {len(relative_paths)} PDF statement(s):")
        for path in relative_paths:
            self._write(f"  {path}")
        return self._confirm("Parse this complete backfill plan? [y/N] ")

    def approve_clean(self, states: tuple[ReviewState, ...]) -> bool:
        if not states:
            return True
        self._write(f"Clean statements ready for bulk approval: {len(states)}")
        for state in states:
            statement = state.statement
            self._write(
                f"  {statement.end_date.isoformat()} | {statement.institution.value} | "
                f"{statement.source_name} | {len(state.rows)} transaction(s)"
            )
        return self._confirm("Approve all clean statements? [y/N] ")

    def skip_rejected(self, source_name: str, reason: str) -> bool:
        self._write(f"Rejected {source_name}: {reason}")
        return self._confirm("Record rejection and continue? [y/N] ")

    def _confirm(self, prompt: str) -> bool:
        self._output.write(prompt)
        self._output.flush()
        return self._input.readline().strip().casefold() in {"y", "yes"}

    def _write(self, value: str) -> None:
        self._output.write(value + "\n")
