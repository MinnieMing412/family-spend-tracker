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
- [ ] AMEX text PDF: the supplied local sample is image-only and is correctly
  rejected as scanned. Obtain a text-bearing AMEX PDF for parser/reconciliation
  acceptance; OCR is outside v1 scope.

## Manual environment and UI

- [ ] Complete install, `--help`, disconnect, and uninstall in a clean macOS user
  environment using [`docs/operations.md`](operations.md).
- [ ] Run one reviewed local sample per institution and verify member assignment,
  category decisions, section totals, and the final import record.
- [ ] Configure a disposable Google workbook and run the opt-in integration test.
- [ ] Complete every Dashboard visual check in
  [`docs/architecture/phase-7-dashboard.md`](architecture/phase-7-dashboard.md).
- [ ] Confirm a second Dashboard provisioning leaves exactly three charts and one
  set of controls.

Do not call the release accepted until every unchecked item above is completed
by the household administrator.
