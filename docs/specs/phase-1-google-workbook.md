# Phase 1 - Google OAuth and Workbook Foundation

**Status:** Ready for agent
**Tracker label:** `ready-for-agent`
**Dependencies:** Phase 0

## Problem Statement

The product needs a secure Google connection and a workbook that is authoritative for household configuration, transactions, rules, and import history. Unsafe provisioning or schema drift could corrupt the ledger.

## Solution

Implement Google OAuth, local connection settings, workbook creation/connection, required worksheet schemas, schema validation, configuration reads, status reporting, and credential disconnection behind the workbook gateway contract.

## User Stories

1. As a household administrator, I want browser-based OAuth, so that no Google password is stored.
2. As a household administrator, I want minimal permissions, so that access is appropriately scoped.
3. As a household administrator, I want a workbook created automatically, so that setup is simple.
4. As a household administrator, I want to connect an existing workbook, so that I control its location.
5. As a household administrator, I want incompatible schemas rejected safely, so that existing data is preserved.
6. As a household administrator, I want members, accounts, categories, and rules loaded before import, so that the workbook remains authoritative.
7. As a household administrator, I want status and disconnect commands, so that local access is visible and revocable.

## Implementation Decisions

- Implement the workbook gateway without leaking Google client objects into domain logic.
- Provision `Transactions`, `Members`, `Accounts`, `Categories`, `Merchant Rules`, `Imports`, and `Dashboard`.
- Seed the finalized category taxonomy, including `Pets` and `Uncategorized`.
- Use stable machine-readable column keys and user-readable headers.
- Attach a workbook schema version and validate it before reads or writes.
- Treat missing, duplicate, renamed, or type-incompatible required columns as explicit compatibility failures.
- Never destructively recreate a worksheet during normal validation.
- Store OAuth material and workbook identity in OS-appropriate user application storage outside the repository.
- Keep credential deletion separate from deleting the Google workbook.

## Testing Decisions

- Run the shared workbook gateway contract against the fake and Google implementations.
- Use a disposable Google workbook for opt-in integration tests.
- Verify create, connect, validate, configuration read, status, and disconnect from the CLI seam.
- Verify malformed sheets fail without modification.
- Verify secrets are absent from terminal output and serialized settings.
- Verify retries do not create duplicate worksheets or headers.

## Out of Scope

- Transaction import commits
- Dashboard formulas and charts
- Parser behavior
- Review behavior

## Further Notes

- Phase 4 will extend the gateway with idempotent approved-import commits.
- Phase 7 owns Dashboard content; this phase provisions only the compatible worksheet and schema marker.
