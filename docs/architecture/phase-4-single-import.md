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

The import ID and transaction IDs are stable across attempts. At command start,
the gateway loads configuration, import history, and transaction rows with one
`values.batchGet` request. Review and duplicate classification use this local,
command-scoped snapshot. A completed review builds one `values.batchUpdate`
containing:

1. Any approved transaction rows absent from the snapshot.
2. Any selected merchant rules absent from the snapshot.
3. One deterministic `complete` import audit row.

Google applies the value ranges atomically, eliminating partially authoritative
transaction/rule/audit states. After success, the gateway updates its local
snapshot so later statements in the same backfill see the newly approved rows
and rules without another provider read. After an ambiguous network failure, it
invalidates the snapshot and reloads authoritative workbook state before retry.
A `complete` audit row causes later attempts to skip.

HTTP 429 responses use bounded exponential backoff across a full quota window.
If retries are exhausted, the CLI reports a concise resume instruction instead
of exposing the raw provider response.

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
cache cleanup/retention. Workbook contract tests assert one snapshot read and
one atomic batch write, then inject failures before and after the provider batch
to prove both outcomes converge without duplicates.
