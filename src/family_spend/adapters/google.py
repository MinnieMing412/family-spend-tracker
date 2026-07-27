"""Google Sheets workbook adapter built on a small API-client boundary."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast

from family_spend.adapters.local import FileCredentialStore
from family_spend.domain.models import (
    AccountConfig,
    ApprovedImport,
    CategoryConfig,
    ImportRecord,
    ImportResult,
    Institution,
    MatchType,
    MemberConfig,
    MerchantRule,
    NormalizedTransaction,
    WorkbookConfig,
)
from family_spend.workbook_schema import CATEGORY_NAMES, SCHEMA_VERSION, WORKSHEET_SCHEMAS

GOOGLE_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


class OAuthCredentials(Protocol):
    """Serializable credentials returned by Google's installed-app flow."""

    def to_json(self) -> str:
        """Serialize credentials using Google's authorized-user format."""
        ...


class OAuthFlow(Protocol):
    """Browser-based installed application authorization flow."""

    def run_local_server(self, *, port: int, open_browser: bool) -> OAuthCredentials:
        """Open consent in a browser and receive the local redirect."""
        ...


FlowBuilder = Callable[[Path, tuple[str, ...]], OAuthFlow]


def _build_installed_app_flow(
    client_secrets: Path,
    scopes: tuple[str, ...],
) -> OAuthFlow:
    """Build Google's installed desktop application OAuth flow."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    return cast(
        OAuthFlow,
        InstalledAppFlow.from_client_secrets_file(str(client_secrets), scopes=scopes),
    )


class GoogleCredentialManager:
    """Run browser OAuth and retain its result in the private credential store."""

    def __init__(
        self,
        store: FileCredentialStore,
        *,
        flow_builder: FlowBuilder = _build_installed_app_flow,
    ) -> None:
        """Create the manager with an injectable browser-flow boundary."""
        self._store = store
        self._flow_builder = flow_builder

    def authorize(self, client_secrets: Path) -> str:
        """Request Sheets-only access and return the stored credential reference."""
        flow = self._flow_builder(client_secrets, (GOOGLE_SHEETS_SCOPE,))
        credentials = flow.run_local_server(port=0, open_browser=True)
        raw = json.loads(credentials.to_json())
        if not isinstance(raw, dict):
            raise ValueError("Google OAuth returned invalid credential data")
        return self._store.save(raw)

    def delete(self, credential_reference: str) -> None:
        """Delete local OAuth credentials without touching the Google workbook."""
        self._store.delete(credential_reference)


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

    credentials = Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
        store.load(store.reference),
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


def _category_id(display_name: str) -> str:
    """Create the stable category ID used by the seeded taxonomy."""
    return display_name.lower().replace(" & ", "_and_").replace(" ", "_")


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

        existing_version = self._client.schema_version(self.workbook_id)
        if existing_version is None:
            self._client.set_schema_version(self.workbook_id, SCHEMA_VERSION)
        elif existing_version != SCHEMA_VERSION:
            raise ValueError("workbook schema version is incompatible")
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
                tuple(
                    (_category_id(name), name, index, True)
                    for index, name in enumerate(CATEGORY_NAMES, start=1)
                ),
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
        self._load_configuration()

    def load_configuration(self) -> WorkbookConfig:
        """Validate and load members, accounts, categories, and merchant rules."""
        self.validate_schema()
        return self._load_configuration()

    def _load_configuration(self) -> WorkbookConfig:
        member_rows = self._client.read_rows(self.workbook_id, "Members")[2:]
        account_rows = self._client.read_rows(self.workbook_id, "Accounts")[2:]
        category_rows = self._client.read_rows(self.workbook_id, "Categories")[2:]
        rule_rows = self._client.read_rows(self.workbook_id, "Merchant Rules")[2:]
        members = tuple(
            MemberConfig(
                member_id=str(row[0]),
                display_name=str(row[1]),
                aliases=tuple(item.strip() for item in str(row[2]).split("|") if item.strip()),
                active=_as_bool(row[3], location="Members.active"),
            )
            for row in member_rows
            if any(value != "" for value in row)
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
            if any(value != "" for value in row)
        )
        categories = tuple(
            CategoryConfig(
                category_id=str(row[0]),
                display_name=str(row[1]),
                sort_order=_as_int(row[2], location="Categories.sort_order"),
                active=_as_bool(row[3], location="Categories.active"),
            )
            for row in category_rows
            if any(value != "" for value in row)
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
            if any(value != "" for value in row)
        )
        return WorkbookConfig(members, accounts, categories, rules)

    def find_import_by_hash(self, statement_hash: str) -> ImportRecord | None:
        """Defer import history lookup to the Phase 4 gateway extension."""
        del statement_hash
        raise NotImplementedError("transaction imports are owned by Phase 4")

    def find_transactions(
        self, fingerprints: tuple[str, ...]
    ) -> tuple[NormalizedTransaction, ...]:
        """Defer transaction lookup to the Phase 4 gateway extension."""
        del fingerprints
        raise NotImplementedError("transaction imports are owned by Phase 4")

    def commit_import(self, approved_import: ApprovedImport) -> ImportResult:
        """Defer approved import commits to the Phase 4 gateway extension."""
        del approved_import
        raise NotImplementedError("transaction imports are owned by Phase 4")


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
