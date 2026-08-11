# Family Spend Tracker

A privacy-conscious macOS CLI for importing AMEX, Bank of America, and Chase statement PDFs into a reviewed, categorized Google Sheets spending ledger.

The project is under active implementation. The current vertical slice imports
one reviewed AMEX or supported Bank of America credit-card statement into Google
Sheets with duplicate protection,
retry-safe writes, and an import audit record.

## Development setup

Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
make check
```

The current command surface is available with:

```bash
.venv/bin/family-spend --help
```

## Connect Google Sheets

Before the first setup:

1. In Google Cloud, enable the Google Sheets API.
2. Create an OAuth client with application type **Desktop app**.
3. Download its client JSON file somewhere outside this repository.

Create a new workbook:

```bash
family-spend setup \
  --client-secrets /path/to/client-secret.json \
  --workbook-name "Family Spending"
```

Or connect an existing compatible workbook:

```bash
family-spend setup \
  --client-secrets /path/to/client-secret.json \
  --workbook-url "https://docs.google.com/spreadsheets/d/WORKBOOK_ID/edit"
```

Setup opens Google authorization in the browser and requests Google Sheets
access plus basic OpenID/email identity so `status` can show the authorized
account. It does not request general Google Drive access. The workbook contains
`Transactions`, `Members`, `Accounts`,
`Categories`, `Merchant Rules`, `Imports`, and `Dashboard`. Machine-readable
column keys occupy the first row, user-facing headers occupy the second row,
and editable data begins on the third row.

Useful lifecycle commands:

```bash
family-spend status
family-spend validate-workbook
family-spend disconnect
```

On macOS, the workbook reference and OAuth credentials are stored separately
under `~/Library/Application Support/Family Spend Tracker/`. `disconnect`
removes these local files and does not delete the Google workbook.

## Review a supported statement

After connecting a workbook and populating its member/account configuration,
import one text-bearing AMEX or Bank of America credit-card statement:

```bash
family-spend import /path/to/statement.pdf
```

The command rejects encrypted, corrupt, scanned/image-only, unsupported, and
ambiguous documents before parsing. It then resolves ownership, normalizes
merchants, applies workbook rules, reconciles statement sections, and displays
a text-labeled review table. Enter `help` at the `review>` prompt to see edit,
filter, bulk-category, rule-save, reconciliation-override, approval, and cancel
commands.

Approval writes the reviewed transactions and any selected merchant rules. The
same statement is skipped on repeat, exact overlapping rows are omitted, and
near-duplicates require an explicit review decision. This command intentionally
accepts exactly one PDF; recursive folder processing belongs to the later
backfill workflow.

Bank of America support covers the consumer credit-card layout documented in
[the Phase 5A architecture note](docs/architecture/phase-5a-bank-of-america-parser.md),
including account-summary totals, transaction and posting dates, continuation
pages, payments/credits, purchases, balance transfers, cash advances, fees, and
interest. A detected but unsupported BOA layout fails with an explicit diagnostic
instead of guessing.

Temporary structured review data is deleted by default. To retain a private,
owner-readable diagnostic record outside the repository, run:

```bash
family-spend import /path/to/statement.pdf --retain-cache
```

The completion message includes the retained cache ID. `family-spend status`
shows the configured cache directory.

## Project documents

- [Product requirements](docs/PRD.md)
- [Agent implementation plan](docs/specs/IMPLEMENTATION_PLAN.md)
- [Agent phase specifications](docs/specs/)
- [Phase 0 contracts](docs/architecture/phase-0-contracts.md)
- [Phase 1 Google workbook architecture](docs/architecture/phase-1-google-workbook.md)
- [Phase 2 PDF and AMEX parser architecture](docs/architecture/phase-2-amex-parser.md)
- [Phase 3 review and rules architecture](docs/architecture/phase-3-review-and-rules.md)
- [Phase 4 single-import architecture](docs/architecture/phase-4-single-import.md)
- [Phase 5A Bank of America parser architecture](docs/architecture/phase-5a-bank-of-america-parser.md)
- [Issue workflow](docs/agents/issue-tracker.md)

## Privacy

Do not commit real bank statements, extracted statement text, Google credentials, local caches, or full account/card numbers. Parser fixtures must be synthetic or irreversibly sanitized.
