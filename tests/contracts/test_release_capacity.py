from __future__ import annotations

import hashlib
import time
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from family_spend.adapters.memory import (
    FixedClock,
    InMemoryCheckpointStore,
    InMemoryStructuredCache,
    InMemoryWorkbookGateway,
)
from family_spend.backfill import BackfillWorkflow
from family_spend.domain.models import (
    ApprovedImport,
    BackfillCheckpoint,
    Institution,
    Money,
    NormalizedStatement,
    NormalizedTransaction,
    ParseResult,
    ReconciliationResult,
    ReconciliationStatus,
    ReviewState,
    StatementTotal,
    TransactionType,
)
from family_spend.ingestion import StatementIngestionService
from family_spend.review import ReviewEngine
from tests.import_helpers import workbook_configuration

_CAPACITY_BUDGET_SECONDS = 5.0


def transactions(count: int) -> tuple[NormalizedTransaction, ...]:
    return tuple(
        NormalizedTransaction(
            transaction_id=f"transaction-{index}",
            institution=Institution.AMEX,
            account_id="ending-10005",
            member_id="member-alpha",
            transaction_date=date(2026, 1, 1),
            posting_date=None,
            raw_description="SYNTHETIC MERCHANT",
            normalized_merchant="SYNTHETIC MERCHANT",
            merchant_location=None,
            amount=Money(Decimal("1.00")),
            transaction_type=TransactionType.PURCHASE,
            category_id="other",
            included_in_spend=True,
            reviewed=True,
            fingerprint=f"fingerprint-{index}",
            statement_id="import-capacity",
            imported_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        for index in range(count)
    )


def statement(items: tuple[NormalizedTransaction, ...]) -> NormalizedStatement:
    return NormalizedStatement(
        statement_id="statement-capacity",
        source_name="synthetic-capacity.pdf",
        source_hash="a" * 64,
        institution=Institution.AMEX,
        account_id="ending-10005",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        closing_date=date(2026, 1, 31),
        transactions=items,
        reported_totals=(),
        warnings=(),
    )


class ReleaseCapacityTests(unittest.TestCase):
    def test_250_statement_backfill_completes_with_per_file_checkpoints(self) -> None:
        class CapacityIngestion(StatementIngestionService):
            def parse(self, source: Path) -> tuple[ParseResult, ...]:
                index = int(source.stem.rsplit("-", 1)[-1])
                amount = Money(Decimal(-(index + 1)))
                item = NormalizedTransaction(
                    transaction_id=f"transaction-{index}",
                    institution=Institution.AMEX,
                    account_id="ending-10005",
                    member_id="member-alpha",
                    transaction_date=date(2026, 1, 1),
                    posting_date=None,
                    raw_description=f"PAYMENT {index}",
                    normalized_merchant=f"PAYMENT {index}",
                    merchant_location=None,
                    amount=amount,
                    transaction_type=TransactionType.PAYMENT,
                    category_id=None,
                    included_in_spend=False,
                    reviewed=False,
                )
                normalized = NormalizedStatement(
                    statement_id=f"statement-{index}",
                    source_name=source.name,
                    source_hash=hashlib.sha256(source.name.encode()).hexdigest(),
                    institution=Institution.AMEX,
                    account_id="ending-10005",
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 31),
                    closing_date=date(2026, 1, 31),
                    transactions=(item,),
                    reported_totals=(StatementTotal("payments", amount),),
                    warnings=(),
                )
                return (ParseResult(normalized),)

        class CapacityReviewer:
            def confirm_plan(self, relative_paths: tuple[str, ...]) -> bool:
                return len(relative_paths) == 250

            def approve_clean(self, states: tuple[ReviewState, ...]) -> bool:
                return len(states) == 250

            def skip_rejected(self, source_name: str, reason: str) -> bool:
                del source_name, reason
                return True

            def review(self, state: ReviewState) -> ReviewState:
                raise AssertionError(f"clean capacity statement required review: {state}")

        class CountingCheckpointStore(InMemoryCheckpointStore):
            def __init__(self) -> None:
                super().__init__()
                self.save_count = 0

            def save(self, checkpoint: BackfillCheckpoint) -> None:
                self.save_count += 1
                super().save(checkpoint)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(250):
                (root / f"statement-{index:03}.pdf").touch()
            engine = ReviewEngine()
            reviewer = CapacityReviewer()
            checkpoints = CountingCheckpointStore()
            workflow = BackfillWorkflow(
                ingestion=CapacityIngestion.__new__(CapacityIngestion),
                review_engine=engine,
                reviewer=reviewer,
                backfill_reviewer=reviewer,
                workbook=InMemoryWorkbookGateway(workbook_configuration()),
                cache=InMemoryStructuredCache(),
                checkpoints=checkpoints,
                clock=FixedClock(datetime(2026, 1, 2, tzinfo=UTC)),
            )

            started = time.monotonic()
            outcome = workflow.execute(root)
            elapsed = time.monotonic() - started

        self.assertEqual(250, outcome.imported)
        self.assertEqual(250, checkpoints.save_count)
        self.assertTrue(outcome.complete)
        self.assertLess(elapsed, _CAPACITY_BUDGET_SECONDS)

    def test_25000_transaction_commit_and_fingerprint_lookup_remain_responsive(self) -> None:
        items = transactions(25_000)
        gateway = InMemoryWorkbookGateway(workbook_configuration())
        approved = ApprovedImport(
            "import-capacity",
            statement(items),
            ReconciliationResult(ReconciliationStatus.MATCHED, ()),
            datetime(2026, 1, 2, tzinfo=UTC),
        )

        started = time.monotonic()
        gateway.commit_import(approved)
        found = gateway.find_transactions(tuple(item.fingerprint or "" for item in items))
        elapsed = time.monotonic() - started

        self.assertEqual(25_000, len(found))
        self.assertLess(elapsed, _CAPACITY_BUDGET_SECONDS)

    def test_1000_transaction_review_model_remains_responsive(self) -> None:
        items = transactions(1_000)

        started = time.monotonic()
        review = ReviewEngine().prepare(statement(items), workbook_configuration())
        elapsed = time.monotonic() - started

        self.assertEqual(1_000, len(review.rows))
        self.assertLess(elapsed, _CAPACITY_BUDGET_SECONDS)


if __name__ == "__main__":
    unittest.main()
