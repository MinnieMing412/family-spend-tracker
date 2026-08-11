# Phase 4 Single-Import Architecture

## End-to-end workflow

`family-spend import <pdf>` accepts exactly one PDF and composes the existing
validation, AMEX parsing, enrichment, reconciliation, and review boundaries.
The workbook is not mutated until review returns an explicit approval. A cancel
or any validation/review failure leaves transactions, rules, and import history
unchanged.

The original PDF bytes produce the statement SHA-256 hash. A completed import
with that hash is skipped before review. Each parsed transaction receives a
second SHA-256 fingerprint derived from its masked account ID, effective date,
exact decimal amount, normalized merchant, and occurrence number among identical
rows in that statement.

Exact fingerprint matches are excluded from the approved write. Similar
merchant activity with the same account and amount within three days is marked
as a near-duplicate, but similarity never removes it automatically: review must
explicitly resolve the row.

## Retry-safe workbook commit

The import ID and transaction IDs are stable across attempts. Workbook commit
uses this sequence:

1. Create or replace one deterministic `pending` import audit row.
2. Read existing transaction IDs and fingerprints, then append only missing rows.
3. Read existing merchant-rule IDs, then append only missing selected rules.
4. Replace the audit row with `complete`.

A retry after any boundary repeats those reads and converges to one audit row,
one copy of each transaction, and one copy of each rule. A `complete` audit row
is authoritative and causes later attempts to skip.

## Privacy and cache lifecycle

Workbook rows contain the approved transaction fields, masked account identity,
fingerprints, and import audit metadata. Parser-only source metadata and full
extracted PDF text are never uploaded.

During review, a structured cache can hold normalized fields, warning codes,
duplicate decisions, and reconciliation state. It does not contain the full PDF
text. The cache is removed in a `finally` path by default. `--retain-cache`
preserves it as JSON in the application cache directory with directory mode
`0700` and file mode `0600`.

## Verification seams

The primary acceptance test invokes the CLI with a synthetic AMEX PDF, scripted
review, isolated settings/cache boundaries, and an in-memory workbook. It checks
the first write, unchanged repeat, cancellation, invalid input, privacy, and
cache cleanup/retention. Workbook contract tests inject failures before the
audit write, after the transaction write, and before final status to prove both
the in-memory and Google Sheets gateways converge on retry.
