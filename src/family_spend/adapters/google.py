"""Google Sheets workbook adapter built on a small API-client boundary."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol, cast

from family_spend.adapters.google_auth import GOOGLE_SHEETS_SCOPE
from family_spend.adapters.local import FileCredentialStore
from family_spend.domain.models import (
    AccountConfig,
    ApprovedImport,
    CategoryConfig,
    ImportRecord,
    ImportResult,
    ImportStatus,
    Institution,
    MatchType,
    MemberConfig,
    MerchantRule,
    Money,
    NormalizedTransaction,
    ReconciliationStatus,
    TransactionType,
    WorkbookConfig,
    validate_masked_account_identifier,
)
from family_spend.workbook_schema import CATEGORY_SEEDS, SCHEMA_VERSION, WORKSHEET_SCHEMAS


class SheetsClient(Protocol):
    """Small, testable subset of Google Sheets operations used by the adapter."""

    def create_workbook(self, title: str) -> str:
        """Create an empty spreadsheet and return its identifier."""
        ...

    def worksheet_names(self, workbook_id: str) -> tuple[str, ...]:
        """Return worksheet titles in workbook order."""
        ...

    def rename_worksheet(self, workbook_id: str, old_name: str, new_name: str) -> None:
        """Rename one worksheet."""
        ...

    def add_worksheet(self, workbook_id: str, name: str) -> None:
        """Append a worksheet with the supplied title."""
        ...

    def schema_version(self, workbook_id: str) -> str | None:
        """Read the application schema version attached to a workbook."""
        ...

    def set_schema_version(self, workbook_id: str, version: str) -> None:
        """Attach or replace the application schema version."""
        ...

    def read_rows(self, workbook_id: str, worksheet: str) -> tuple[tuple[object, ...], ...]:
        """Read all populated rows from one worksheet."""
        ...

    def write_rows(
        self,
        workbook_id: str,
        worksheet: str,
        start_row: int,
        rows: tuple[tuple[object, ...], ...],
    ) -> None:
        """Replace rows beginning at the one-based row number."""
        ...


GoogleServiceBuilder = Callable[[], Any]


def _authorized_sheets_service(store: FileCredentialStore) -> Any:
    """Build an authorized Google Sheets v4 service from locally stored OAuth data."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credential_data = store.load(store.reference)
    credential_data.pop("_family_spend_identity", None)
    credentials = Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
        credential_data,
        scopes=[GOOGLE_SHEETS_SCOPE],
    )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        refreshed = json.loads(credentials.to_json())
        if not isinstance(refreshed, dict):
            raise ValueError("Google returned invalid refreshed credentials")
        store.save(refreshed)
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


class GoogleApiSheetsClient:
    """Translate the small Sheets boundary into official Google API calls."""

    def __init__(
        self,
        credential_store: FileCredentialStore,
        *,
        service_builder: GoogleServiceBuilder | None = None,
    ) -> None:
        """Create a client that builds an authorized service for each operation."""
        self._credential_store = credential_store
        self._service_builder = service_builder or (
            lambda: _authorized_sheets_service(self._credential_store)
        )

    def _spreadsheets(self) -> Any:
        """Return the official API's spreadsheets resource."""
        return self._service_builder().spreadsheets()

    def _metadata(self, workbook_id: str) -> dict[str, Any]:
        """Read worksheet properties and developer metadata."""
        result = self._spreadsheets().get(
            spreadsheetId=workbook_id,
            fields=(
                "sheets.properties(sheetId,title),"
                "developerMetadata(metadataId,metadataKey,metadataValue)"
            ),
        ).execute()
        return cast(dict[str, Any], result)

    def create_workbook(self, title: str) -> str:
        """Create a Google spreadsheet and return its identifier."""
        result = self._spreadsheets().create(
            body={"properties": {"title": title}},
            fields="spreadsheetId",
        ).execute()
        return str(cast(dict[str, Any], result)["spreadsheetId"])

    def worksheet_names(self, workbook_id: str) -> tuple[str, ...]:
        """Return worksheet titles in workbook order."""
        sheets = self._metadata(workbook_id).get("sheets", [])
        return tuple(str(sheet["properties"]["title"]) for sheet in sheets)

    def _sheet_id(self, workbook_id: str, name: str) -> int:
        """Resolve a worksheet title to its numeric Google sheet ID."""
        for sheet in self._metadata(workbook_id).get("sheets", []):
            properties = sheet["properties"]
            if properties["title"] == name:
                return int(properties["sheetId"])
        raise ValueError(f"worksheet not found: {name}")

    def rename_worksheet(self, workbook_id: str, old_name: str, new_name: str) -> None:
        """Rename one worksheet through an atomic batch update."""
        self._spreadsheets().batchUpdate(
            spreadsheetId=workbook_id,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": self._sheet_id(workbook_id, old_name),
                                "title": new_name,
                            },
                            "fields": "title",
                        }
                    }
                ]
            },
        ).execute()

    def add_worksheet(self, workbook_id: str, name: str) -> None:
        """Append one worksheet through an atomic batch update."""
        self._spreadsheets().batchUpdate(
            spreadsheetId=workbook_id,
            body={"requests": [{"addSheet": {"properties": {"title": name}}}]},
        ).execute()

    def schema_version(self, workbook_id: str) -> str | None:
        """Read the application schema version from developer metadata."""
        for item in self._metadata(workbook_id).get("developerMetadata", []):
            if item.get("metadataKey") == "family_spend_schema_version":
                return str(item.get("metadataValue"))
        return None

    def set_schema_version(self, workbook_id: str, version: str) -> None:
        """Create or update the workbook-level schema-version metadata."""
        existing = next(
            (
                item
                for item in self._metadata(workbook_id).get("developerMetadata", [])
                if item.get("metadataKey") == "family_spend_schema_version"
            ),
            None,
        )
        request: dict[str, Any]
        if existing is None:
            request = {
                "createDeveloperMetadata": {
                    "developerMetadata": {
                        "metadataKey": "family_spend_schema_version",
                        "metadataValue": version,
                        "visibility": "DOCUMENT",
                        "location": {"spreadsheet": True},
                    }
                }
            }
        else:
            request = {
                "updateDeveloperMetadata": {
                    "dataFilters": [
                        {"developerMetadataLookup": {"metadataId": existing["metadataId"]}}
                    ],
                    "developerMetadata": {"metadataValue": version},
                    "fields": "metadataValue",
                }
            }
        self._spreadsheets().batchUpdate(
            spreadsheetId=workbook_id,
            body={"requests": [request]},
        ).execute()

    def read_rows(self, workbook_id: str, worksheet: str) -> tuple[tuple[object, ...], ...]:
        """Read populated rows from one worksheet."""
        escaped = worksheet.replace("'", "''")
        result = self._spreadsheets().values().get(
            spreadsheetId=workbook_id,
            range=f"'{escaped}'",
            majorDimension="ROWS",
        ).execute()
        rows = cast(dict[str, Any], result).get("values", [])
        return tuple(tuple(cast(list[object], row)) for row in rows)

    def write_rows(
        self,
        workbook_id: str,
        worksheet: str,
        start_row: int,
        rows: tuple[tuple[object, ...], ...],
    ) -> None:
        """Write rows with RAW input so IDs and machine keys are preserved."""
        escaped = worksheet.replace("'", "''")
        self._spreadsheets().values().update(
            spreadsheetId=workbook_id,
            range=f"'{escaped}'!A{start_row}",
            valueInputOption="RAW",
            body={"majorDimension": "ROWS", "values": [list(row) for row in rows]},
        ).execute()


def _as_bool(value: object, *, location: str) -> bool:
    """Parse a strict workbook boolean or raise a compatibility error."""
    if isinstance(value, bool):
        return value
    if value in ("TRUE", "true"):
        return True
    if value in ("FALSE", "false"):
        return False
    raise ValueError(f"{location} must contain TRUE or FALSE")


def _as_int(value: object, *, location: str) -> int:
    """Parse a workbook integer while rejecting booleans and fractional values."""
    if isinstance(value, bool):
        raise ValueError(f"{location} must contain an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError(f"{location} must contain an integer")


def _non_empty_string(value: object, *, location: str) -> str:
    """Return a stripped string or raise a workbook compatibility error."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location} must not be empty")
    return value.strip()


def _normalized_row(
    row: tuple[object, ...],
    *,
    width: int,
    location: str,
) -> tuple[object, ...]:
    """Pad omitted trailing blanks while rejecting rows wider than the schema."""
    if len(row) > width:
        raise ValueError(f"{location} has more values than the workbook schema")
    return (*row, *("" for _ in range(width - len(row))))


def _validate_unique_row_ids(
    rows: tuple[tuple[object, ...], ...],
    *,
    location: str,
) -> None:
    """Reject blank or duplicate IDs in one authoritative worksheet."""
    ids = tuple(_non_empty_string(row[0], location=f"{location}.id") for row in rows)
    if len(set(ids)) != len(ids):
        raise ValueError(f"{location} IDs must be unique")


def _validate_transaction_rows(rows: tuple[tuple[object, ...], ...]) -> None:
    """Validate IDs and value types in authoritative transaction rows."""
    _validate_unique_row_ids(rows, location="Transactions")
    fingerprints: list[str] = []
    for row in rows:
        fingerprints.append(
            _non_empty_string(row[1], location="Transactions.fingerprint")
        )
        _non_empty_string(row[2], location="Transactions.statement_id")
        Institution(_non_empty_string(row[3], location="Transactions.institution"))
        validate_masked_account_identifier(
            _non_empty_string(row[4], location="Transactions.account_id")
        )
        _non_empty_string(row[5], location="Transactions.member_id")
        date.fromisoformat(
            _non_empty_string(row[6], location="Transactions.transaction_date")
        )
        if row[7]:
            date.fromisoformat(str(row[7]))
        _non_empty_string(row[8], location="Transactions.raw_description")
        _non_empty_string(row[9], location="Transactions.normalized_merchant")
        Money(Decimal(_non_empty_string(row[11], location="Transactions.amount")))
        transaction_type = TransactionType(
            _non_empty_string(row[12], location="Transactions.transaction_type")
        )
        included = _as_bool(row[14], location="Transactions.included_in_spend")
        if included:
            _non_empty_string(row[13], location="Transactions.category_id")
        elif row[13] and not isinstance(row[13], str):
            raise ValueError("Transactions.category_id must contain text")
        _as_bool(row[15], location="Transactions.reviewed")
        datetime.fromisoformat(
            _non_empty_string(row[16], location="Transactions.imported_at")
        )
        if transaction_type in {TransactionType.PAYMENT, TransactionType.TRANSFER} and included:
            raise ValueError("non-spending transaction type cannot be included in spend")
    if len(set(fingerprints)) != len(fingerprints):
        raise ValueError("Transactions fingerprints must be unique")


def _validate_import_rows(rows: tuple[tuple[object, ...], ...]) -> None:
    """Validate IDs and value types in authoritative import audit rows."""
    _validate_unique_row_ids(rows, location="Imports")
    statement_hashes: list[str] = []
    for row in rows:
        _non_empty_string(row[1], location="Imports.source_name")
        statement_hashes.append(
            _non_empty_string(row[2], location="Imports.statement_hash")
        )
        Institution(_non_empty_string(row[3], location="Imports.institution"))
        validate_masked_account_identifier(
            _non_empty_string(row[4], location="Imports.account_id")
        )
        _non_empty_string(row[5], location="Imports.statement_period")
        reconciliation = ReconciliationStatus(
            _non_empty_string(row[6], location="Imports.reconciliation_status")
        )
        Money(Decimal(_non_empty_string(row[7], location="Imports.reconciliation_difference")))
        if reconciliation is ReconciliationStatus.OVERRIDDEN:
            _non_empty_string(row[8], location="Imports.override_reason")
        if _as_int(row[9], location="Imports.transaction_count") < 0:
            raise ValueError("Imports.transaction_count must not be negative")
        ImportStatus(_non_empty_string(row[10], location="Imports.status"))
        datetime.fromisoformat(
            _non_empty_string(row[11], location="Imports.imported_at")
        )
    if len(set(statement_hashes)) != len(statement_hashes):
        raise ValueError("Imports statement hashes must be unique")


def _data_rows(
    worksheet: str,
    raw_rows: tuple[tuple[object, ...], ...],
) -> tuple[tuple[object, ...], ...]:
    """Normalize populated data rows to the worksheet's declared width."""
    schema = next(item for item in WORKSHEET_SCHEMAS if item.name == worksheet)
    return tuple(
        _normalized_row(
            row,
            width=len(schema.columns),
            location=worksheet,
        )
        for row in raw_rows
        if any(value != "" for value in row)
    )


def _validate_sheet_data(
    worksheet: str,
    raw_rows: tuple[tuple[object, ...], ...],
) -> None:
    """Validate IDs and cell value types for one authoritative worksheet."""
    if worksheet == "Dashboard":
        return
    rows = _data_rows(worksheet, raw_rows)
    if worksheet == "Transactions":
        _validate_transaction_rows(rows)
        return
    if worksheet == "Imports":
        _validate_import_rows(rows)
        return
    _validate_unique_row_ids(rows, location=worksheet)
    for row in rows:
        if worksheet == "Members":
            _non_empty_string(row[1], location="Members.display_name")
            if not isinstance(row[2], str):
                raise ValueError("Members.aliases must contain text")
            _as_bool(row[3], location="Members.active")
        elif worksheet == "Accounts":
            Institution(_non_empty_string(row[1], location="Accounts.institution"))
            validate_masked_account_identifier(
                _non_empty_string(row[2], location="Accounts.masked_identifier")
            )
            _non_empty_string(row[3], location="Accounts.default_member_id")
            _non_empty_string(row[4], location="Accounts.display_name")
            _as_bool(row[5], location="Accounts.active")
        elif worksheet == "Categories":
            _non_empty_string(row[1], location="Categories.display_name")
            _as_int(row[2], location="Categories.sort_order")
            _as_bool(row[3], location="Categories.active")
        elif worksheet == "Merchant Rules":
            MatchType(_non_empty_string(row[1], location="Merchant Rules.match_type"))
            _non_empty_string(row[2], location="Merchant Rules.match_value")
            _non_empty_string(row[3], location="Merchant Rules.normalized_merchant")
            _non_empty_string(row[4], location="Merchant Rules.category_id")
            _as_int(row[5], location="Merchant Rules.priority")
            _as_bool(row[6], location="Merchant Rules.active")
            if row[7]:
                datetime.fromisoformat(str(row[7]))


def _configuration_from_rows(
    member_rows: tuple[tuple[object, ...], ...],
    account_rows: tuple[tuple[object, ...], ...],
    category_rows: tuple[tuple[object, ...], ...],
    rule_rows: tuple[tuple[object, ...], ...],
) -> WorkbookConfig:
    """Build configuration and validate IDs plus cross-sheet references."""
    members = tuple(
        MemberConfig(
            member_id=str(row[0]),
            display_name=str(row[1]),
            aliases=tuple(item.strip() for item in str(row[2]).split("|") if item.strip()),
            active=_as_bool(row[3], location="Members.active"),
        )
        for row in member_rows
    )
    accounts = tuple(
        AccountConfig(
            account_id=str(row[0]),
            institution=Institution(str(row[1])),
            masked_identifier=str(row[2]),
            default_member_id=str(row[3]),
            display_name=str(row[4]),
            active=_as_bool(row[5], location="Accounts.active"),
        )
        for row in account_rows
    )
    categories = tuple(
        CategoryConfig(
            category_id=str(row[0]),
            display_name=str(row[1]),
            sort_order=_as_int(row[2], location="Categories.sort_order"),
            active=_as_bool(row[3], location="Categories.active"),
        )
        for row in category_rows
    )
    rules = tuple(
        MerchantRule(
            rule_id=str(row[0]),
            match_type=MatchType(str(row[1])),
            match_value=str(row[2]),
            normalized_merchant=str(row[3]),
            category_id=str(row[4]),
            priority=_as_int(row[5], location="Merchant Rules.priority"),
            active=_as_bool(row[6], location="Merchant Rules.active"),
            updated_at=datetime.fromisoformat(str(row[7])) if row[7] else None,
        )
        for row in rule_rows
    )
    return WorkbookConfig(members, accounts, categories, rules)


def _transaction_from_row(row: tuple[object, ...]) -> NormalizedTransaction:
    """Convert one validated workbook row back into the normalized contract."""
    return NormalizedTransaction(
        transaction_id=str(row[0]),
        fingerprint=str(row[1]),
        statement_id=str(row[2]),
        institution=Institution(str(row[3])),
        account_id=str(row[4]),
        member_id=str(row[5]),
        transaction_date=date.fromisoformat(str(row[6])),
        posting_date=date.fromisoformat(str(row[7])) if row[7] else None,
        raw_description=str(row[8]),
        normalized_merchant=str(row[9]),
        merchant_location=str(row[10]) if row[10] else None,
        amount=Money(Decimal(str(row[11]))),
        transaction_type=TransactionType(str(row[12])),
        category_id=str(row[13]) if row[13] else None,
        included_in_spend=_as_bool(row[14], location="Transactions.included_in_spend"),
        reviewed=_as_bool(row[15], location="Transactions.reviewed"),
        imported_at=datetime.fromisoformat(str(row[16])),
    )


def _transaction_row(transaction: NormalizedTransaction) -> tuple[object, ...]:
    """Serialize only approved normalized fields required by the workbook."""
    if transaction.fingerprint is None or transaction.statement_id is None:
        raise ValueError("approved transaction requires fingerprint and import ID")
    if transaction.member_id is None or transaction.imported_at is None:
        raise ValueError("approved transaction requires owner and imported timestamp")
    return (
        transaction.transaction_id,
        transaction.fingerprint,
        transaction.statement_id,
        transaction.institution.value,
        transaction.account_id,
        transaction.member_id,
        transaction.transaction_date.isoformat(),
        transaction.posting_date.isoformat() if transaction.posting_date else "",
        transaction.raw_description,
        transaction.normalized_merchant,
        transaction.merchant_location or "",
        str(transaction.amount.amount),
        transaction.transaction_type.value,
        transaction.category_id or "",
        transaction.included_in_spend,
        transaction.reviewed,
        transaction.imported_at.isoformat(),
    )


def _reconciliation_difference(approved: ApprovedImport) -> Decimal:
    return sum(
        (line.difference.amount for line in approved.reconciliation.lines),
        Decimal("0"),
    )


def _import_row(approved: ApprovedImport, status: ImportStatus) -> tuple[object, ...]:
    statement = approved.statement
    return (
        approved.import_id,
        statement.source_name,
        statement.source_hash,
        statement.institution.value,
        statement.account_id,
        f"{statement.start_date.isoformat()}/{statement.end_date.isoformat()}",
        approved.reconciliation.status.value,
        str(_reconciliation_difference(approved)),
        approved.reconciliation.override_reason or "",
        len(statement.transactions),
        status.value,
        approved.reviewed_at.isoformat(),
    )


def _merchant_rule_row(rule: MerchantRule) -> tuple[object, ...]:
    return (
        rule.rule_id,
        rule.match_type.value,
        rule.match_value,
        rule.normalized_merchant,
        rule.category_id,
        rule.priority,
        rule.active,
        rule.updated_at.isoformat() if rule.updated_at else "",
    )


class GoogleWorkbookGateway:
    """Workbook gateway bound to one Google spreadsheet identifier."""

    def __init__(self, client: SheetsClient, workbook_id: str) -> None:
        """Create a gateway backed by the supplied Sheets client."""
        self._client = client
        self._workbook_id = workbook_id

    @property
    def workbook_id(self) -> str:
        """Return the connected spreadsheet identifier."""
        return self._workbook_id

    def provision_schema(self) -> None:
        """Idempotently create required worksheets, headers, and categories."""
        names = self._client.worksheet_names(self.workbook_id)
        required_names = tuple(schema.name for schema in WORKSHEET_SCHEMAS)
        existing_version = self._client.schema_version(self.workbook_id)
        if existing_version not in (None, SCHEMA_VERSION):
            raise ValueError("workbook schema version is incompatible")
        configuration_rows: dict[str, tuple[tuple[object, ...], ...]] = {}
        for schema in WORKSHEET_SCHEMAS:
            if schema.name not in names or not schema.columns:
                continue
            existing_rows = self._client.read_rows(self.workbook_id, schema.name)
            expected_headers = (
                tuple(column.key for column in schema.columns),
                tuple(column.header for column in schema.columns),
            )
            if existing_rows and (
                len(existing_rows) < 2 or existing_rows[:2] != expected_headers
            ):
                raise ValueError(f"worksheet columns are incompatible: {schema.name}")
            if existing_rows:
                _validate_sheet_data(schema.name, existing_rows[2:])
                if schema.name in {"Members", "Accounts", "Categories", "Merchant Rules"}:
                    configuration_rows[schema.name] = _data_rows(
                        schema.name,
                        existing_rows[2:],
                    )

        seeded_category_rows = tuple(
            (category.category_id, category.display_name, index, True)
            for index, category in enumerate(CATEGORY_SEEDS, start=1)
        )
        _configuration_from_rows(
            configuration_rows.get("Members", ()),
            configuration_rows.get("Accounts", ()),
            configuration_rows.get("Categories", seeded_category_rows),
            configuration_rows.get("Merchant Rules", ()),
        )

        if "Transactions" not in names and names == ("Sheet1",):
            self._client.rename_worksheet(
                self.workbook_id,
                "Sheet1",
                "Transactions",
            )
            names = ("Transactions",)
        for name in required_names:
            if name not in names:
                self._client.add_worksheet(self.workbook_id, name)
                names = (*names, name)

        if existing_version is None:
            self._client.set_schema_version(self.workbook_id, SCHEMA_VERSION)
        for schema in WORKSHEET_SCHEMAS:
            if not schema.columns:
                continue
            expected_headers = (
                tuple(column.key for column in schema.columns),
                tuple(column.header for column in schema.columns),
            )
            existing_rows = self._client.read_rows(self.workbook_id, schema.name)
            if not existing_rows:
                self._client.write_rows(
                    self.workbook_id,
                    schema.name,
                    1,
                    expected_headers,
                )
            elif len(existing_rows) < 2 or existing_rows[:2] != expected_headers:
                raise ValueError(f"worksheet columns are incompatible: {schema.name}")
        category_rows = self._client.read_rows(self.workbook_id, "Categories")
        if len(category_rows) == 2:
            self._client.write_rows(
                self.workbook_id,
                "Categories",
                3,
                seeded_category_rows,
            )

    def validate_schema(self) -> None:
        """Reject missing, renamed, reordered, or type-incompatible workbook data."""
        if self._client.schema_version(self.workbook_id) != SCHEMA_VERSION:
            raise ValueError("workbook schema version is missing or incompatible")
        names = self._client.worksheet_names(self.workbook_id)
        for schema in WORKSHEET_SCHEMAS:
            if schema.name not in names:
                raise ValueError(f"required worksheet is missing: {schema.name}")
            if not schema.columns:
                continue
            rows = self._client.read_rows(self.workbook_id, schema.name)
            expected_keys = tuple(column.key for column in schema.columns)
            expected_headers = tuple(column.header for column in schema.columns)
            if len(rows) < 2 or rows[0] != expected_keys or rows[1] != expected_headers:
                raise ValueError(f"worksheet columns are incompatible: {schema.name}")
            _validate_sheet_data(schema.name, rows[2:])
        self._load_configuration()

    def load_configuration(self) -> WorkbookConfig:
        """Validate and load members, accounts, categories, and merchant rules."""
        self.validate_schema()
        return self._load_configuration()

    def latest_successful_import(self) -> datetime | None:
        """Return the newest completed import timestamp recorded in the workbook."""
        rows = _data_rows(
            "Imports",
            self._client.read_rows(self.workbook_id, "Imports")[2:],
        )
        timestamps: list[datetime] = []
        for row in rows:
            if len(row) < 12 or str(row[10]) != "complete" or not row[11]:
                continue
            timestamps.append(datetime.fromisoformat(str(row[11])))
        return max(timestamps, default=None)

    def unresolved_exception_count(self) -> int:
        """Count failed, pending, or unreconciled import audit rows."""
        rows = _data_rows(
            "Imports",
            self._client.read_rows(self.workbook_id, "Imports")[2:],
        )
        return sum(
            str(row[10]) in {ImportStatus.PENDING.value, ImportStatus.FAILED.value}
            or str(row[6])
            in {
                ReconciliationStatus.DISCREPANCY.value,
                ReconciliationStatus.UNAVAILABLE.value,
            }
            for row in rows
        )

    def find_import_by_hash(self, statement_hash: str) -> ImportRecord | None:
        """Find an authoritative staged or completed import by statement hash."""
        import_rows = _data_rows(
            "Imports",
            self._client.read_rows(self.workbook_id, "Imports")[2:],
        )
        transaction_rows = _data_rows(
            "Transactions",
            self._client.read_rows(self.workbook_id, "Transactions")[2:],
        )
        for row in import_rows:
            if str(row[2]) != statement_hash:
                continue
            import_id = str(row[0])
            transaction_ids = tuple(
                str(transaction[0])
                for transaction in transaction_rows
                if str(transaction[2]) == import_id
            )
            return ImportRecord(
                import_id=import_id,
                statement_hash=statement_hash,
                status=ImportStatus(str(row[10])),
                transaction_ids=transaction_ids,
                imported_at=datetime.fromisoformat(str(row[11])) if row[11] else None,
            )
        return None

    def find_transactions(
        self,
        fingerprints: tuple[str, ...],
    ) -> tuple[NormalizedTransaction, ...]:
        """Return authoritative rows with one of the requested fingerprints."""
        requested = set(fingerprints)
        rows = _data_rows(
            "Transactions",
            self._client.read_rows(self.workbook_id, "Transactions")[2:],
        )
        _validate_transaction_rows(rows)
        return tuple(_transaction_from_row(row) for row in rows if str(row[1]) in requested)

    def transactions_in_window(
        self,
        account_id: str,
        start_date: date,
        end_date: date,
    ) -> tuple[NormalizedTransaction, ...]:
        """Return authoritative rows in an inclusive account/date window."""
        rows = _data_rows(
            "Transactions",
            self._client.read_rows(self.workbook_id, "Transactions")[2:],
        )
        _validate_transaction_rows(rows)
        transactions = tuple(_transaction_from_row(row) for row in rows)
        return tuple(
            transaction
            for transaction in transactions
            if transaction.account_id == account_id
            and start_date <= (transaction.posting_date or transaction.transaction_date)
            <= end_date
        )

    def commit_import(self, approved_import: ApprovedImport) -> ImportResult:
        """Converge a staged import to one complete audit row and stable ledger rows."""
        statement = approved_import.statement
        if any(transaction.fingerprint is None for transaction in statement.transactions):
            raise ValueError("approved transactions require fingerprints")

        import_rows = _data_rows(
            "Imports",
            self._client.read_rows(self.workbook_id, "Imports")[2:],
        )
        matching_index = next(
            (
                index
                for index, row in enumerate(import_rows)
                if str(row[2]) == statement.source_hash
            ),
            None,
        )
        if matching_index is not None:
            existing = import_rows[matching_index]
            if str(existing[0]) != approved_import.import_id:
                raise ValueError("pending import ID does not match deterministic retry ID")
            if ImportStatus(str(existing[10])) is ImportStatus.COMPLETE:
                transaction_ids = tuple(
                    transaction.transaction_id for transaction in statement.transactions
                )
                return ImportResult(
                    approved_import.import_id,
                    ImportStatus.SKIPPED,
                    transaction_ids,
                    "statement already imported",
                )
            import_row_number = matching_index + 3
        else:
            import_row_number = len(import_rows) + 3

        self._client.write_rows(
            self.workbook_id,
            "Imports",
            import_row_number,
            (_import_row(approved_import, ImportStatus.PENDING),),
        )

        transaction_rows = _data_rows(
            "Transactions",
            self._client.read_rows(self.workbook_id, "Transactions")[2:],
        )
        existing_transaction_ids = {str(row[0]) for row in transaction_rows}
        existing_fingerprints = {str(row[1]) for row in transaction_rows}
        missing_transactions = tuple(
            transaction
            for transaction in statement.transactions
            if transaction.transaction_id not in existing_transaction_ids
            and transaction.fingerprint not in existing_fingerprints
        )
        if missing_transactions:
            self._client.write_rows(
                self.workbook_id,
                "Transactions",
                len(transaction_rows) + 3,
                tuple(_transaction_row(transaction) for transaction in missing_transactions),
            )

        rule_rows = _data_rows(
            "Merchant Rules",
            self._client.read_rows(self.workbook_id, "Merchant Rules")[2:],
        )
        existing_rule_ids = {str(row[0]) for row in rule_rows}
        missing_rules = tuple(
            rule
            for rule in approved_import.merchant_rules
            if rule.rule_id not in existing_rule_ids
        )
        if missing_rules:
            self._client.write_rows(
                self.workbook_id,
                "Merchant Rules",
                len(rule_rows) + 3,
                tuple(_merchant_rule_row(rule) for rule in missing_rules),
            )

        self._client.write_rows(
            self.workbook_id,
            "Imports",
            import_row_number,
            (_import_row(approved_import, ImportStatus.COMPLETE),),
        )
        transaction_ids = tuple(
            transaction.transaction_id for transaction in statement.transactions
        )
        return ImportResult(
            approved_import.import_id,
            ImportStatus.COMPLETE,
            transaction_ids,
            f"Imported {len(transaction_ids)} transactions.",
        )

    def _load_configuration(self) -> WorkbookConfig:
        member_rows = _data_rows(
            "Members",
            self._client.read_rows(self.workbook_id, "Members")[2:],
        )
        account_rows = _data_rows(
            "Accounts",
            self._client.read_rows(self.workbook_id, "Accounts")[2:],
        )
        category_rows = _data_rows(
            "Categories",
            self._client.read_rows(self.workbook_id, "Categories")[2:],
        )
        rule_rows = _data_rows(
            "Merchant Rules",
            self._client.read_rows(self.workbook_id, "Merchant Rules")[2:],
        )
        return _configuration_from_rows(
            member_rows,
            account_rows,
            category_rows,
            rule_rows,
        )

class GoogleWorkbookFactory:
    """Create or connect Google workbook gateways using one Sheets client."""

    def __init__(self, client: SheetsClient) -> None:
        """Create a factory for an authorized Sheets client."""
        self._client = client

    def create(self, title: str) -> GoogleWorkbookGateway:
        """Create a spreadsheet and return its bound gateway."""
        return GoogleWorkbookGateway(self._client, self._client.create_workbook(title))

    def connect(self, workbook_id: str) -> GoogleWorkbookGateway:
        """Return a gateway bound to an existing spreadsheet."""
        return GoogleWorkbookGateway(self._client, workbook_id)
