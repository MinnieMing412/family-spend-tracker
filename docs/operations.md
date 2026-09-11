# Family Spend Tracker Operations Guide

This guide covers installation, configuration, normal operation, recovery, and
removal for the macOS-oriented v1 CLI. Keep all real statements and Google
credentials outside the repository.

## Install and upgrade

Python 3.12 or newer is required. From a trusted checkout:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install .
.venv/bin/family-spend --help
```

Run `.venv/bin/python -m pip install --upgrade .` after pulling a newer release.
The examples below use `family-spend`; substitute `.venv/bin/family-spend` when
the virtual environment is not activated.

## First-time Google setup

Enable the Google Sheets API in a Google Cloud project, create an OAuth 2.0
client whose application type is **Desktop app**, and download its JSON outside
the checkout. Then create a workbook:

```bash
family-spend setup \
  --client-secrets /private/path/client-secret.json \
  --workbook-name "Family Spending"
```

To use an already-compatible workbook, pass its standard Google Sheets URL with
`--workbook-url`. Setup requests Sheets, OpenID, and email identity scopes; it
does not request general Drive access.

## Configure the workbook

Do not rename sheets, reorder the first two header rows, or change their machine
keys. Editable configuration begins on row 3:

- `Members`: a stable member ID, display name, statement aliases, and `TRUE` in
  `Active`. Separate multiple aliases with the format already shown in the sheet.
- `Accounts`: a stable account ID, institution (`amex`, `bank_of_america`, or
  `chase`), masked identifier, default member ID, display name, and active flag.
  Store only an `ending-12345`-style masked value, never the full number.
- `Categories`: stable category ID, display name, sort order, and active flag.
- `Merchant Rules`: normally created during review; rules may also be disabled
  by changing `Active` to `FALSE`.

Run `family-spend validate-workbook` after structural edits. Direct edits to
approved `Transactions` rows are authoritative and automatically recalculate the
Dashboard.

## Routine import and historical backfill

Import one supported text-bearing statement and complete the interactive review:

```bash
family-spend import /private/path/statement.pdf
```

For historical folders:

```bash
family-spend backfill /private/path/statements
family-spend backfill /private/path/statements --resume
```

Backfill previews relative paths before parsing, checkpoints every processed
statement, and prints a per-file status and next action. Reusing `--resume` is
safe: the workbook, not the checkpoint, is the final proof of completion.

## Cache retention and deletion

Temporary structured data is deleted after success, cancellation, parse/review
failure, workbook failure, or interruption. Add `--retain-cache` to `import` or
`backfill` only when diagnostics are needed. Retained JSON contains normalized
fields, not the PDF or its extracted page text, and uses owner-only permissions.

`family-spend status` prints the cache directory. Delete only the named
`cache-<id>.json` file after diagnostics; do not delete or move the source PDF as
part of cache cleanup.

## Recovery and troubleshooting

| Symptom | Safe next action |
| --- | --- |
| No workbook is connected | Run `setup`, then `validate-workbook`. |
| Workbook schema is incompatible | Restore sheet names and the two header rows, then rerun `validate-workbook`. |
| PDF is scanned, encrypted, corrupt, or unsupported | Obtain a text-bearing supported statement; no rows were uploaded. |
| Review fails or is cancelled | Correct the review input and retry the same statement; incomplete review uploads nothing. |
| Workbook write fails before rows are confirmed | Retry the same statement. Stable import IDs and fingerprints prevent duplicates. |
| Workbook write may have partially completed | Retry the same statement; the pending import converges to one completed record. |
| Backfill is incomplete | Follow its per-file next action and rerun with `--resume`. |
| Cache cleanup fails | Run `status`, delete only the named cache file, then retry safely. |
| Authorization is stale or revoked | Run `disconnect`, then `setup` with the Desktop-app client JSON. |

Never paste OAuth tokens, full account numbers, raw statement text, or real PDFs
into an issue, log, test fixture, or Git commit.

## Status, disconnect, and uninstall

```bash
family-spend status
family-spend disconnect
```

Disconnect removes local OAuth credentials and settings but never deletes the
Google workbook. Disconnect before uninstalling when local access should be
revoked, then remove the package and virtual environment:

```bash
.venv/bin/python -m pip uninstall family-spend-tracker
```

The Google account's security settings can also revoke the application's grant.

## Manual release acceptance

Before household use, validate one local sample from AMEX, Bank of America, and
Chase without copying it into the checkout. Confirm each sample's institution,
masked account, dates, transaction count, section reconciliation, member mapping,
and review behavior. Approve only after those values match the statement.

In Google Sheets, complete the Dashboard checklist in
[`docs/architecture/phase-7-dashboard.md`](architecture/phase-7-dashboard.md).
Confirm charts do not overlap, filters update every output, direct transaction
edits recalculate, refunds remain negative, and a second provisioning still
leaves exactly three charts.
