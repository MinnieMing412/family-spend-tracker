# Phase 8 Release Hardening Architecture

Phase 8 turns the complete feature set into a repeatable release gate. It does
not add institutions or product behavior; it verifies and hardens existing
privacy, recovery, capacity, installation, and operating boundaries.

## Privacy and local recovery

All private JSON writes use an owner-only directory, an owner-only temporary
file, and an atomic replacement. A failed replacement removes its temporary
file. Import cache writes fail closed before upload, default cleanup runs across
success, cancellation, review failure, workbook failure, and interruption, and
cleanup failures identify the safe cache ID and manual next action.

`make check` scans every tracked and non-ignored file for statement PDFs,
credential filenames, extracted-text artifacts, access-token shapes, serialized
OAuth secrets, and full account/card-number shapes. The scanner reports only a
path and reason, never the matching content. The Bank of America deposit fixture
uses only a masked account identifier.

## Retry and backfill recovery

Single-import workbook failures are translated at the workflow boundary. The
message distinguishes a failure before confirmed rows from a failure after rows
may have been written, suppresses provider details, and always directs the user
to retry the same statement through the idempotent commit protocol.

Backfill summaries contain relative paths, final statuses, and explicit next
actions. Relative paths preserve enough context for nested folders without
exposing the absolute household directory.

## Capacity and external validation

The deterministic release suite exercises a 250-statement backfill with one
checkpoint per statement, a 25,000-transaction workbook commit and fingerprint
lookup, and construction of a 1,000-row review model. Each capacity case has a
five-second local/CI budget; current tests operate on synthetic records and do
not require a network or real PDFs.

Real institution samples and Google chart rendering remain local/manual release
checks because neither private statements nor a household workbook belongs in
CI. The operations guide records the required parser, review, reconciliation,
and Dashboard acceptance checklist.

The household release accepts Bank of America and Chase text-bearing layouts.
AMEX remains implemented and fixture-tested for text-bearing statements but is
deferred from household acceptance: all three available real samples are
image-only and correctly fail closed, while OCR remains outside this phase.
