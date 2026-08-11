from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path

from family_spend.adapters.local import FileStructuredCache
from family_spend.adapters.memory import (
    FixedClock,
    InMemorySettingsStore,
    InMemoryStructuredCache,
    InMemoryWorkbookGateway,
)
from family_spend.application import FamilySpendApplication
from family_spend.cli import main
from family_spend.domain.models import LocalSettings
from family_spend.review import ReviewEngine
from tests.import_helpers import (
    ApprovingReviewer,
    CancellingReviewer,
    build_ingestion,
    workbook_configuration,
    write_statement,
)


class SingleImportCliAcceptanceTests(unittest.TestCase):
    def _application(
        self,
        workbook: InMemoryWorkbookGateway,
        reviewer: ApprovingReviewer | CancellingReviewer,
        cache: InMemoryStructuredCache | FileStructuredCache,
        engine: ReviewEngine,
    ) -> FamilySpendApplication:
        settings = InMemorySettingsStore()
        settings.save(LocalSettings("workbook-1", "memory:credentials"))
        return FamilySpendApplication(
            settings=settings,
            workbook=workbook,
            ingestion=build_ingestion(),
            review_engine=engine,
            reviewer=reviewer,
            structured_cache=cache,
            clock=FixedClock(datetime(2026, 8, 10, 12, 0, tzinfo=UTC)),
        )

    @staticmethod
    def _run(
        application: FamilySpendApplication,
        path: Path,
        *,
        retain_cache: bool = False,
    ) -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        arguments = ["import", str(path)]
        if retain_cache:
            arguments.append("--retain-cache")
        exit_code = main(
            arguments,
            application=application,
            stdout=stdout,
            stderr=stderr,
        )
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_approved_statement_writes_once_and_repeat_is_unchanged(self) -> None:
        engine = ReviewEngine()
        reviewer = ApprovingReviewer(engine, save_rule=True)
        workbook = InMemoryWorkbookGateway(workbook_configuration())
        cache = InMemoryStructuredCache()
        application = self._application(workbook, reviewer, cache, engine)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statement.pdf"
            write_statement(path)
            statement_hash = hashlib.sha256(path.read_bytes()).hexdigest()

            first = self._run(application, path)
            second = self._run(application, path)

        transactions = workbook.transactions_in_window(
            "ending-10005", date.min, date.max
        )
        audit = workbook.find_import_by_hash(statement_hash)
        self.assertEqual((0, ""), (first[0], first[2]))
        self.assertIn("import complete", first[1])
        self.assertEqual((0, ""), (second[0], second[2]))
        self.assertIn("already imported", second[1])
        self.assertEqual(1, reviewer.call_count)
        self.assertEqual(8, len(transactions))
        self.assertIsNotNone(audit)
        self.assertEqual(8, len(audit.transaction_ids) if audit else 0)
        self.assertEqual(1, len(workbook.load_configuration().merchant_rules))
        self.assertTrue(all(item.source_metadata == () for item in transactions))
        self.assertTrue(all(item.account_id == "ending-10005" for item in transactions))
        self.assertIsNone(cache.load(f"cache-{statement_hash[:20]}"))

    def test_cancelled_review_writes_nothing_and_cleans_cache(self) -> None:
        engine = ReviewEngine()
        workbook = InMemoryWorkbookGateway(workbook_configuration())
        cache = InMemoryStructuredCache()
        application = self._application(
            workbook,
            CancellingReviewer(engine),
            cache,
            engine,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statement.pdf"
            write_statement(path)
            statement_hash = hashlib.sha256(path.read_bytes()).hexdigest()

            result = self._run(application, path)

        self.assertEqual((0, ""), (result[0], result[2]))
        self.assertIn("Review cancelled", result[1])
        self.assertIsNone(workbook.find_import_by_hash(statement_hash))
        self.assertEqual(
            (),
            workbook.transactions_in_window("ending-10005", date.min, date.max),
        )
        self.assertIsNone(cache.load(f"cache-{statement_hash[:20]}"))

    def test_invalid_pdf_fails_before_any_workbook_write(self) -> None:
        engine = ReviewEngine()
        workbook = InMemoryWorkbookGateway(workbook_configuration())
        cache = InMemoryStructuredCache()
        application = self._application(
            workbook,
            ApprovingReviewer(engine),
            cache,
            engine,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.pdf"
            path.write_bytes(b"not a PDF")

            result = self._run(application, path)

        self.assertNotEqual(0, result[0])
        self.assertEqual("", result[1])
        self.assertIsNone(workbook.latest_successful_import())
        self.assertEqual(
            (),
            workbook.transactions_in_window("ending-10005", date.min, date.max),
        )

    def test_retained_cache_is_private_structured_and_contains_no_pdf_text(self) -> None:
        engine = ReviewEngine()
        workbook = InMemoryWorkbookGateway(workbook_configuration())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = FileStructuredCache(root / "cache")
            application = self._application(
                workbook,
                ApprovingReviewer(engine),
                cache,
                engine,
            )
            path = root / "statement.pdf"
            write_statement(path)
            statement_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            cache_id = f"cache-{statement_hash[:20]}"

            result = self._run(application, path, retain_cache=True)

            cache_path = cache.path_for(cache_id)
            raw_cache = cache_path.read_text(encoding="utf-8")
            parsed_cache = json.loads(raw_cache)
            self.assertEqual((0, ""), (result[0], result[2]))
            self.assertIn(cache_id, result[1])
            self.assertEqual(0o600, stat.S_IMODE(cache_path.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(cache_path.parent.stat().st_mode))
            self.assertEqual(statement_hash, parsed_cache["statement_hash"])
            self.assertIn("transactions", parsed_cache["fields"])
            self.assertNotIn("Synthetic Card Statement", raw_cache)
            self.assertNotIn("Account Ending", raw_cache)
            self.assertNotIn("Payments and Credits", raw_cache)


if __name__ == "__main__":
    unittest.main()
