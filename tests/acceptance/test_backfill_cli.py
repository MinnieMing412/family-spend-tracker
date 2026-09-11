from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from family_spend.adapters.memory import (
    FixedClock,
    InMemoryCheckpointStore,
    InMemorySettingsStore,
    InMemoryStructuredCache,
    InMemoryWorkbookGateway,
)
from family_spend.application import FamilySpendApplication
from family_spend.cli import main
from family_spend.domain.models import (
    ApprovedImport,
    BackfillCheckpoint,
    ImportResult,
    LocalSettings,
    MatchType,
    MerchantRule,
    ReviewState,
    WorkbookConfig,
)
from family_spend.review import ReviewEngine
from tests.import_helpers import (
    FIXTURE,
    ApprovingReviewer,
    build_ingestion,
    workbook_configuration,
    write_statement,
)
from tests.pdf_factory import write_text_pdf


class BackfillDecisions:
    def __init__(
        self,
        *,
        confirm: bool = True,
        skip_rejected: bool = True,
    ) -> None:
        self.paths: tuple[str, ...] = ()
        self.clean_names: tuple[str, ...] = ()
        self.skip = skip_rejected
        self.confirm = confirm

    def confirm_plan(self, relative_paths: tuple[str, ...]) -> bool:
        self.paths = relative_paths
        return self.confirm

    def approve_clean(self, states: tuple[ReviewState, ...]) -> bool:
        self.clean_names = tuple(state.statement.source_name for state in states)
        return True

    def skip_rejected(self, source_name: str, reason: str) -> bool:
        return self.skip


def clean_configuration() -> WorkbookConfig:
    base = workbook_configuration()
    merchants = (
        "COFFEE SHOP",
        "COFFEE SHOPPE",
        "MARKETPLACE SEATTLE WA",
        "ONLINE STORE",
        "TRAVEL SERVICE",
        "ANNUAL MEMBERSHIP FEE",
        "INTEREST CHARGE",
        "RETURNED MERCHANDISE",
    )
    rules = tuple(
        MerchantRule(
            f"rule-{index}",
            MatchType.EXACT,
            merchant,
            merchant,
            "other",
            index,
            True,
        )
        for index, merchant in enumerate(merchants, start=1)
    )
    return replace(base, merchant_rules=rules)


class BackfillCliAcceptanceTests(unittest.TestCase):
    def _application(
        self,
        workbook: InMemoryWorkbookGateway,
        decisions: BackfillDecisions,
        checkpoints: InMemoryCheckpointStore,
        reviewer: ApprovingReviewer,
    ) -> FamilySpendApplication:
        settings = InMemorySettingsStore()
        settings.save(LocalSettings("workbook-1", "memory:credentials"))
        engine = ReviewEngine()
        return FamilySpendApplication(
            settings=settings,
            workbook=workbook,
            ingestion=build_ingestion(),
            review_engine=engine,
            reviewer=reviewer,
            backfill_reviewer=decisions,
            structured_cache=InMemoryStructuredCache(),
            checkpoint_store=checkpoints,
            clock=FixedClock(datetime(2026, 8, 10, 12, 0, tzinfo=UTC)),
        )

    @staticmethod
    def _run(
        application: FamilySpendApplication,
        root: Path,
        *,
        resume: bool = False,
    ) -> tuple[int, str, str]:
        stdout, stderr = StringIO(), StringIO()
        arguments = ["backfill", str(root)]
        if resume:
            arguments.append("--resume")
        code = main(arguments, application=application, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_nested_plan_bulk_approval_and_exception_routing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested").mkdir()
            later = root / "a-later.pdf"
            earlier = root / "nested" / "z-earlier.pdf"
            later_text = FIXTURE.read_text().replace("06/15/26", "07/15/26")
            later_text = later_text.replace("COFFEE SHOP", "COFFEE SHOPPE")
            write_text_pdf(later, tuple(later_text.split("\f")))
            write_statement(earlier)
            (root / "ignored.txt").write_text("not a statement")
            decisions = BackfillDecisions()
            engine = ReviewEngine()
            reviewer = ApprovingReviewer(engine)
            workbook = InMemoryWorkbookGateway(clean_configuration())
            settings = InMemorySettingsStore()
            settings.save(LocalSettings("workbook-1", "memory:credentials"))
            application = FamilySpendApplication(
                settings=settings,
                workbook=workbook,
                ingestion=build_ingestion(),
                review_engine=engine,
                reviewer=reviewer,
                backfill_reviewer=decisions,
                structured_cache=InMemoryStructuredCache(),
                checkpoint_store=InMemoryCheckpointStore(),
                clock=FixedClock(datetime(2026, 8, 10, 12, 0, tzinfo=UTC)),
            )

            result = self._run(application, root)

        self.assertEqual((0, ""), (result[0], result[2]))
        self.assertEqual(("a-later.pdf", "nested/z-earlier.pdf"), decisions.paths)
        self.assertEqual(("z-earlier.pdf", "a-later.pdf"), decisions.clean_names)
        self.assertIn("Discovered: 2", result[1])
        self.assertIn("imported: 2", result[1])
        self.assertEqual(1, reviewer.call_count)

    def test_resume_does_not_trust_stale_checkpoint_over_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "statement.pdf"
            write_statement(path)
            statement_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            root_id = hashlib.sha256(str(root).encode()).hexdigest()
            checkpoints = InMemoryCheckpointStore()
            checkpoints.save(BackfillCheckpoint(root_id, "stale-plan", (statement_hash,)))
            decisions = BackfillDecisions()
            engine = ReviewEngine()
            reviewer = ApprovingReviewer(engine)
            workbook = InMemoryWorkbookGateway(workbook_configuration())
            application = self._application(workbook, decisions, checkpoints, reviewer)

            result = self._run(application, root, resume=True)

        self.assertEqual((0, ""), (result[0], result[2]))
        self.assertIn("imported: 1", result[1])
        self.assertIsNotNone(workbook.find_import_by_hash(statement_hash))

    def test_rejected_file_is_counted_only_after_explicit_skip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broken.pdf").write_bytes(b"not a PDF")
            decisions = BackfillDecisions(skip_rejected=True)
            engine = ReviewEngine()
            application = self._application(
                InMemoryWorkbookGateway(workbook_configuration()),
                decisions,
                InMemoryCheckpointStore(),
                ApprovingReviewer(engine),
            )

            result = self._run(application, root)

        self.assertEqual((0, ""), (result[0], result[2]))
        self.assertIn("rejected: 1", result[1])
        self.assertIn("unresolved: 0", result[1])
        self.assertIn("- broken.pdf: rejected", result[1])
        self.assertIn("next: replace the PDF", result[1])

    def test_interruption_checkpoints_and_resume_finishes_remaining_work(self) -> None:
        class InterruptSecondCommitGateway(InMemoryWorkbookGateway):
            def __init__(self) -> None:
                super().__init__(clean_configuration())
                self.commit_count = 0
                self.interrupted = False

            def commit_import(self, approved_import: ApprovedImport) -> ImportResult:
                self.commit_count += 1
                if self.commit_count == 2 and not self.interrupted:
                    self.interrupted = True
                    raise RuntimeError("simulated interruption")
                return super().commit_import(approved_import)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.pdf"
            second = root / "second.pdf"
            write_statement(first)
            write_statement(
                second,
                replace_text=("COFFEE SHOP", "COFFEE SHOPPE"),
            )
            decisions = BackfillDecisions()
            engine = ReviewEngine()
            reviewer = ApprovingReviewer(engine)
            workbook = InterruptSecondCommitGateway()
            checkpoints = InMemoryCheckpointStore()
            application = self._application(
                workbook, decisions, checkpoints, reviewer
            )

            interrupted = self._run(application, root)
            resumed = self._run(application, root, resume=True)

        self.assertIn("Backfill incomplete", interrupted[1])
        self.assertIn("imported: 1", interrupted[1])
        self.assertIn("unresolved: 1", interrupted[1])
        self.assertIn(": unresolved; next: retry the same backfill with --resume", interrupted[1])
        self.assertIn("Backfill complete", resumed[1])
        self.assertIn("imported: 1", resumed[1])
        self.assertIn("duplicates: 1", resumed[1])
        self.assertEqual(3, workbook.commit_count)

    def test_250_file_preview_cancels_before_any_pdf_is_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(250):
                nested = root / f"year-{index // 50}"
                nested.mkdir(exist_ok=True)
                (nested / f"statement-{index:03}.pdf").write_bytes(b"preview only")
            decisions = BackfillDecisions(confirm=False)
            engine = ReviewEngine()
            application = self._application(
                InMemoryWorkbookGateway(workbook_configuration()),
                decisions,
                InMemoryCheckpointStore(),
                ApprovingReviewer(engine),
            )

            started = time.monotonic()
            result = self._run(application, root)
            elapsed = time.monotonic() - started

        self.assertEqual(250, len(decisions.paths))
        self.assertIn("skipped: 250", result[1])
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
