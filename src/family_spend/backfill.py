"""Recursive, resumable historical statement backfill orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from family_spend.domain.models import (
    BackfillCheckpoint,
    ImportStatus,
    ReviewState,
    ReviewStatus,
)
from family_spend.imports import PreparedImport, SingleImportWorkflow
from family_spend.ingestion import StatementIngestionService, discover_pdfs
from family_spend.ports import (
    BackfillReviewPort,
    CheckpointStore,
    Clock,
    ReviewPort,
    StructuredCache,
    WorkbookGateway,
)
from family_spend.review import ReviewEngine


@dataclass(frozen=True, slots=True)
class BackfillOutcome:
    """Final observable counts for one backfill run."""

    discovered: int
    imported: int = 0
    duplicates: int = 0
    skipped: int = 0
    rejected: int = 0
    unresolved: int = 0
    complete: bool = True

    def summary(self) -> str:
        status = "complete" if self.complete else "incomplete"
        return (
            f"Backfill {status}. Discovered: {self.discovered}; "
            f"imported: {self.imported}; duplicates: {self.duplicates}; "
            f"skipped: {self.skipped}; rejected: {self.rejected}; "
            f"unresolved: {self.unresolved}."
        )


@dataclass(frozen=True, slots=True)
class _PlanItem:
    path: Path
    relative_path: str
    prepared: PreparedImport | None
    error: str | None = None


class _ApprovedCleanReviewer:
    def __init__(self, engine: ReviewEngine) -> None:
        self._engine = engine

    def review(self, state: ReviewState) -> ReviewState:
        if not state.is_clean:
            raise ValueError("only clean statements can use bulk approval")
        return self._engine.decide(state, status=ReviewStatus.APPROVED)


class BackfillWorkflow:
    """Plan and execute a sequential folder import through single imports."""

    def __init__(
        self,
        *,
        ingestion: StatementIngestionService,
        review_engine: ReviewEngine,
        reviewer: ReviewPort,
        backfill_reviewer: BackfillReviewPort,
        workbook: WorkbookGateway,
        cache: StructuredCache,
        checkpoints: CheckpointStore,
        clock: Clock,
    ) -> None:
        self._ingestion = ingestion
        self._review_engine = review_engine
        self._reviewer = reviewer
        self._backfill_reviewer = backfill_reviewer
        self._workbook = workbook
        self._cache = cache
        self._checkpoints = checkpoints
        self._clock = clock

    def execute(
        self,
        root: Path,
        *,
        resume: bool = False,
        retain_cache: bool = False,
    ) -> BackfillOutcome:
        root = root.expanduser().resolve()
        if not root.is_dir():
            raise ValueError("backfill source must be a directory")
        paths = discover_pdfs(root)
        relative_paths = tuple(path.relative_to(root).as_posix() for path in paths)
        if not self._backfill_reviewer.confirm_plan(relative_paths):
            return BackfillOutcome(
                discovered=len(paths), skipped=len(paths), complete=False
            )

        root_id = hashlib.sha256(str(root).encode()).hexdigest()
        plan_hash = self._plan_hash(root, paths)
        checkpoint = self._checkpoints.load(root_id) if resume else None
        completed_hints = set(
            checkpoint.completed_statement_hashes if checkpoint is not None else ()
        )
        failed_names = set(
            checkpoint.failed_source_names
            if checkpoint is not None and checkpoint.plan_hash == plan_hash
            else ()
        )

        preview_workflow = self._single_workflow()
        plan: list[_PlanItem] = []
        for path, relative_path in zip(paths, relative_paths, strict=True):
            try:
                prepared = preview_workflow.prepare(path)
                plan.append(_PlanItem(path, relative_path, prepared))
            except Exception as error:
                plan.append(_PlanItem(path, relative_path, None, str(error)))
        plan.sort(
            key=lambda item: (
                item.prepared is None,
                item.prepared.state.statement.closing_date
                if item.prepared is not None
                else item.relative_path.casefold(),
                item.relative_path.casefold(),
            )
        )

        clean_states = tuple(
            item.prepared.state
            for item in plan
            if item.prepared is not None
            and not (
                item.prepared.existing_import is not None
                and item.prepared.existing_import.status is ImportStatus.COMPLETE
            )
            and item.prepared.state.is_clean
        )
        if clean_states and not self._backfill_reviewer.approve_clean(clean_states):
            self._save_checkpoint(root_id, plan_hash, completed_hints, failed_names)
            return BackfillOutcome(
                discovered=len(paths), unresolved=len(clean_states), complete=False
            )
        approved_clean_hashes = {
            state.statement.source_hash for state in clean_states
        }

        imported = duplicates = skipped = rejected = unresolved = 0
        clean_reviewer = _ApprovedCleanReviewer(self._review_engine)
        for item in plan:
            if item.prepared is None:
                if item.relative_path in failed_names:
                    rejected += 1
                    continue
                if self._backfill_reviewer.skip_rejected(
                    item.path.name, item.error or "statement could not be parsed"
                ):
                    rejected += 1
                    failed_names.add(item.relative_path)
                    self._save_checkpoint(
                        root_id, plan_hash, completed_hints, failed_names
                    )
                    continue
                unresolved += 1
                self._save_checkpoint(root_id, plan_hash, completed_hints, failed_names)
                return BackfillOutcome(
                    len(paths), imported, duplicates, skipped, rejected, unresolved, False
                )

            preview_hash = item.prepared.state.statement.source_hash
            if preview_hash in completed_hints:
                authoritative = self._workbook.find_import_by_hash(preview_hash)
                if authoritative is not None and authoritative.status is ImportStatus.COMPLETE:
                    duplicates += 1
                    continue
            try:
                workflow = self._single_workflow()
                prepared = workflow.prepare(item.path)
                source_hash = prepared.state.statement.source_hash
                selected_reviewer = (
                    clean_reviewer
                    if prepared.state.is_clean
                    and source_hash in approved_clean_hashes
                    else self._reviewer
                )
                outcome = workflow.execute_prepared(
                    prepared,
                    retain_cache=retain_cache,
                    reviewer=selected_reviewer,
                )
            except Exception:
                unresolved += 1
                self._save_checkpoint(root_id, plan_hash, completed_hints, failed_names)
                return BackfillOutcome(
                    len(paths), imported, duplicates, skipped, rejected, unresolved, False
                )

            if outcome.disposition == "duplicate_statement":
                duplicates += 1
                completed_hints.add(source_hash)
            elif outcome.disposition == "cancelled":
                skipped += 1
            elif outcome.status is ImportStatus.COMPLETE:
                imported += 1
                completed_hints.add(source_hash)
            else:
                unresolved += 1
            self._save_checkpoint(root_id, plan_hash, completed_hints, failed_names)

        self._checkpoints.delete(root_id)
        return BackfillOutcome(
            len(paths), imported, duplicates, skipped, rejected, unresolved, not unresolved
        )

    def _single_workflow(self) -> SingleImportWorkflow:
        return SingleImportWorkflow(
            ingestion=self._ingestion,
            review_engine=self._review_engine,
            reviewer=self._reviewer,
            workbook=self._workbook,
            configuration=self._workbook.load_configuration(),
            cache=self._cache,
            clock=self._clock,
        )

    def _save_checkpoint(
        self,
        root_id: str,
        plan_hash: str,
        completed: set[str],
        failed: set[str],
    ) -> None:
        self._checkpoints.save(
            BackfillCheckpoint(
                root_id=root_id,
                plan_hash=plan_hash,
                completed_statement_hashes=tuple(sorted(completed)),
                failed_source_names=tuple(sorted(failed)),
            )
        )

    @staticmethod
    def _plan_hash(root: Path, paths: tuple[Path, ...]) -> str:
        digest = hashlib.sha256()
        for path in paths:
            stat = path.stat()
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(f"\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
        return digest.hexdigest()
