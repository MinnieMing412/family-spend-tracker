# v1 Release Checklist

Automated checks run with `make check`. Manual checks must use private local
samples and a disposable Google workbook; never copy those artifacts into this
repository.

## Automated

- [x] Full unit, contract, acceptance, lint, type, compilation, and privacy gate.
- [x] Owner-only credential, settings, checkpoint, and retained-cache writes.
- [x] Cleanup across success, cancellation, parse/review/workbook failure, and
  interruption, including failed atomic-write cleanup.
- [x] Actionable retry messages for review, cache, workbook, and backfill failures.
- [x] Synthetic 250-statement backfill with 250 checkpoints.
- [x] Synthetic 25,000-transaction commit and fingerprint lookup.
- [x] Synthetic 1,000-transaction review-model construction.
- [x] Fresh Google Dashboard grid expansion occurs before wide value writes.

## Local institution samples

Validated on 2026-09-10 without uploading or copying source files:

- [x] Bank of America text PDF: detected correctly, 13 transactions, masked
  account output, and matched reconciliation across 3 lines.
- [x] Chase text PDF: detected correctly, 11 transactions, masked account output,
  and matched reconciliation across 6 lines.
- [x] AMEX release decision: deferred from household v1 acceptance. The supplied
  local sample is image-only and is correctly rejected as scanned; OCR remains
  outside v1 scope.

Additional May samples validated on 2026-09-21 without uploading or copying:

- [x] Bank of America text PDF: 12 transactions, masked account output, and
  matched reconciliation across 3 lines.
- [x] Chase text PDF ending 9174: 6 transactions, masked account output, and
  matched reconciliation across 6 lines.
- [x] Chase text PDF ending 7466: 40 transactions, masked account output, and
  matched reconciliation across 6 lines.
- [x] The May and April AMEX PDFs are also image-only and are correctly rejected
  as scanned, confirming the release deferral rather than parser acceptance.

## Manual environment and UI

- [x] Complete install, `--help`, disconnected-state behavior, and uninstall in
  an isolated macOS Python 3.12 environment using
  [`docs/operations.md`](operations.md).
- [ ] Run one reviewed local Bank of America sample and one reviewed local Chase
  sample; verify member assignment, category decisions, section totals, and the
  final import record.
- [x] Configure a disposable Google workbook and run the opt-in integration test.
- [x] Complete every Dashboard visual check in
  [`docs/architecture/phase-7-dashboard.md`](architecture/phase-7-dashboard.md).
- [x] Confirm a second Dashboard provisioning leaves exactly three charts and one
  set of controls.

Dashboard validation completed on 2026-09-21 with synthetic QA-only rows. The
live test covered every transaction type, an unapproved row, a refund exceeding
its category purchases, all five controls, direct edits to amount, category,
merchant, member, and type, chart-support recalculation, and idempotent
reprovisioning. Manual Chrome review confirmed descending category bars,
chronological months, labeled member series, negative values, and non-overlapping
charts and support data.

The isolated installation lifecycle completed on 2026-09-24 in a new temporary
Python 3.12 virtual environment and private application-data directory. It built
and installed the wheel with production dependencies, displayed CLI help,
reported the disconnected state safely, uninstalled the package, and removed
the installed executable.

Do not call the release accepted until every unchecked item above is completed
by the household administrator.
