# Phase 1 Google Workbook Architecture

## Boundaries

- `GoogleCredentialManager` owns browser OAuth and requests only
  `https://www.googleapis.com/auth/spreadsheets`.
- `FileCredentialStore` stores OAuth JSON in a private `0600` file.
- `FileSettingsStore` stores only the workbook ID and credential-file reference.
- `GoogleApiSheetsClient` translates a small, SDK-style boundary into official
  Google Sheets API calls.
- `GoogleWorkbookGateway` owns provisioning, compatibility validation, and
  authoritative configuration reads.

Google client objects do not cross these adapter boundaries.

## Workbook contract

Schema version `1` is attached as workbook-level developer metadata. Required
worksheets are:

1. `Transactions`
2. `Members`
3. `Accounts`
4. `Categories`
5. `Merchant Rules`
6. `Imports`
7. `Dashboard`

For structured worksheets, row 1 contains stable machine keys, row 2 contains
user-facing headers, and data begins at row 3. `Dashboard` is provisioned as an
empty derived-view surface for Phase 7.

Provisioning is retry-safe. It adds missing pieces to a newly created workbook,
but it does not replace incompatible headers, overwrite existing category data,
or recreate worksheets during validation.

## Test strategy

- CLI acceptance tests use in-memory credential and workbook boundaries.
- The workbook contract runs against `GoogleWorkbookGateway` with an in-memory
  Sheets API client.
- OAuth tests inject the external browser-flow boundary and verify the exact
  requested scope.
- Filesystem contract tests use isolated temporary directories.
- Live Google access is never required by the default test suite or CI.
