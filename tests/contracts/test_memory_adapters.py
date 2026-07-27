from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from family_spend.adapters.memory import (
    InMemorySettingsStore,
    InMemoryWorkbookGateway,
    StaticParserRegistry,
    StaticStatementParser,
)
from family_spend.domain.models import (
    ApprovedImport,
    ImportStatus,
    Institution,
    LocalSettings,
    Money,
    NormalizedStatement,
    NormalizedTransaction,
    ParseResult,
    ReconciliationResult,
    ReconciliationStatus,
    TransactionType,
    WorkbookConfig,
)


class SettingsStoreContractTests(unittest.TestCase):
    def test_settings_can_be_saved_loaded_and_deleted(self) -> None:
        store = InMemorySettingsStore()
        settings = LocalSettings(
            workbook_id="workbook-1",
            credential_reference="keyring:family-spend",
        )

        self.assertIsNone(store.load())
        store.save(settings)
        self.assertEqual(settings, store.load())
        store.delete()
        self.assertIsNone(store.load())


class WorkbookGatewayContractTests(unittest.TestCase):
    def test_workbook_configuration_is_read_through_the_gateway(self) -> None:
        configuration = WorkbookConfig(
            members=(),
            accounts=(),
            categories=(),
            merchant_rules=(),
        )
        gateway = InMemoryWorkbookGateway(configuration)

        gateway.validate_schema()

        self.assertEqual(configuration, gateway.load_configuration())

    def test_approved_import_is_observable_by_statement_hash(self) -> None:
        configuration = WorkbookConfig((), (), (), ())
        gateway = InMemoryWorkbookGateway(configuration)
        transaction = NormalizedTransaction(
            transaction_id="txn-1",
            institution=Institution.AMEX,
            account_id="ending-12345",
            member_id="member-1",
            transaction_date=date(2026, 5, 1),
            posting_date=None,
            raw_description="Example merchant",
            normalized_merchant="EXAMPLE MERCHANT",
            merchant_location=None,
            amount=Money(Decimal("12.34")),
            transaction_type=TransactionType.PURCHASE,
            category_id="dining",
            included_in_spend=True,
            reviewed=True,
            fingerprint="fingerprint-1",
            statement_id="statement-1",
        )
        statement = NormalizedStatement(
            statement_id="statement-1",
            source_name="sample.pdf",
            source_hash="a" * 64,
            institution=Institution.AMEX,
            account_id="ending-12345",
            start_date=date(2026, 4, 9),
            end_date=date(2026, 5, 8),
            closing_date=date(2026, 5, 8),
            transactions=(transaction,),
            reported_totals=(),
            warnings=(),
        )
        approved_import = ApprovedImport(
            import_id="import-1",
            statement=statement,
            reconciliation=ReconciliationResult(
                status=ReconciliationStatus.MATCHED,
                lines=(),
            ),
            reviewed_at=datetime(2026, 5, 9, tzinfo=UTC),
        )

        result = gateway.commit_import(approved_import)
        stored_import = gateway.find_import_by_hash(statement.source_hash)

        self.assertEqual(ImportStatus.COMPLETE, result.status)
        self.assertIsNotNone(stored_import)
        assert stored_import is not None
        self.assertEqual("import-1", stored_import.import_id)


class ParserAdapterContractTests(unittest.TestCase):
    def test_static_parser_result_is_available_through_the_registry(self) -> None:
        @dataclass
        class TestPdf:
            path: Path
            source_name: str
            sha256: str
            page_count: int

        statement = NormalizedStatement(
            statement_id="statement-1",
            source_name="sample.pdf",
            source_hash="a" * 64,
            institution=Institution.AMEX,
            account_id="ending-12345",
            start_date=date(2026, 4, 9),
            end_date=date(2026, 5, 8),
            closing_date=date(2026, 5, 8),
            transactions=(),
            reported_totals=(),
            warnings=(),
        )
        expected = ParseResult(statement)
        parser = StaticStatementParser(expected)
        registry = StaticParserRegistry(parser)
        source = TestPdf(
            path=Path("sample.pdf"),
            source_name="sample.pdf",
            sha256="a" * 64,
            page_count=1,
        )

        selected_parser = registry.parser_for(source)

        self.assertEqual(expected, selected_parser.parse(source))


if __name__ == "__main__":
    unittest.main()
