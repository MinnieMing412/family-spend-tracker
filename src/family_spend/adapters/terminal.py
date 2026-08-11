"""Accessible line-oriented terminal review table."""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import TextIO

from family_spend.domain.models import MatchType, ReviewRow, ReviewState, ReviewStatus
from family_spend.review import (
    ReviewEngine,
    edit_review_row,
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
        exceptions_only = False
        override_reason: str | None = None
        self._write("Commands: approve, cancel, filter all|exceptions, edit, bulk-category,")
        self._write("          save-rule, resolve-duplicate, override, help")
        while True:
            self._render(current, exceptions_only=exceptions_only)
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
                    return self._engine.decide(
                        current,
                        status=ReviewStatus.APPROVED,
                        override_reason=override_reason,
                    )
                if command == "filter" and len(parts) == 2:
                    if parts[1] not in {"all", "exceptions"}:
                        raise ValueError("filter must be all or exceptions")
                    exceptions_only = parts[1] == "exceptions"
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
                if command == "bulk-category" and len(parts) >= 3:
                    category = parts[1]
                    self._validate_reference("category", category, current)
                    rows = list(current.rows)
                    for value in parts[2:]:
                        index = self._row_index(value, current.rows)
                        rows[index] = edit_review_row(rows[index], "category", category)
                    current = self._engine.decide(
                        current,
                        status=ReviewStatus.PENDING,
                        rows=tuple(rows),
                        override_reason=override_reason,
                    )
                    continue
                if command == "save-rule" and len(parts) == 3:
                    index = self._row_index(parts[1], current.rows)
                    rule = save_rule_for_row(current.rows[index], MatchType(parts[2].casefold()))
                    current = replace(
                        current,
                        saved_rule_ids=(*current.saved_rule_ids, rule.rule_id),
                        saved_rules=(*current.saved_rules, rule),
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
                    self._help()
                    continue
                raise ValueError("unknown or incomplete review command")
            except (ValueError, IndexError) as error:
                self._write(f"Error: {error}")

    def _render(self, state: ReviewState, *, exceptions_only: bool) -> None:
        self._write("")
        self._write(
            "# | Date       | Member       | Merchant             | "
            "Amount      | Category       | Flags"
        )
        self._write(
            "--+------------+--------------+----------------------+"
            "-------------+----------------+----------------"
        )
        displayed = 0
        for index, row in enumerate(state.rows, start=1):
            if exceptions_only and not row.is_exception:
                continue
            displayed += 1
            transaction = row.current
            flags = self._flags(row)
            self._write(
                f"{index:<2}| {transaction.transaction_date.isoformat():<11}| "
                f"{(transaction.member_id or 'UNRESOLVED')[:12]:<13}| "
                f"{transaction.normalized_merchant[:20]:<21}| "
                f"{transaction.amount.amount!s:>11} | "
                f"{(transaction.category_id or 'N/A')[:14]:<15}| {flags}"
            )
        if displayed == 0:
            self._write("No rows match the current filter.")
        self._write(
            f"Reconciliation: {state.reconciliation.status.value}; "
            f"clean: {'yes' if state.is_clean else 'no'}; "
            f"saved rules: {len(state.saved_rules)}"
        )

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
    def _row_index(value: str, rows: tuple[ReviewRow, ...]) -> int:
        index = int(value) - 1
        if index < 0 or index >= len(rows):
            raise IndexError("row index is out of range")
        return index

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
        self._write("edit ROW member|merchant|date|amount|type|category VALUE")
        self._write("bulk-category CATEGORY ROW [ROW ...]")
        self._write("save-rule ROW exact|contains")
        self._write("resolve-duplicate ROW")
        self._write("override NON-EMPTY REASON; override clear")
        self._write("filter all|exceptions; approve; cancel")

    def _write(self, value: str) -> None:
        self._output.write(value + "\n")
