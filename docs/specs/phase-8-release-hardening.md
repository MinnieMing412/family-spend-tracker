# Phase 8 - Privacy, Recovery, Performance, and Release Hardening

**Status:** Ready for agent
**Tracker label:** `ready-for-agent`
**Dependencies:** Phases 5A, 5B, 6, and 7

## Problem Statement

The complete feature handles sensitive financial data and long-running imports. It is not ready for household use until redaction, cleanup, retry recovery, parser coverage, performance, documentation, and release gates are proven end to end.

## Solution

Run the complete acceptance matrix, harden error paths and privacy behavior, meet backfill performance targets, validate all supported institutions with real local samples, and produce installation and operating documentation.

## User Stories

1. As a household administrator, I want sensitive values absent from logs and Git, so that household data remains private.
2. As a household administrator, I want failures to explain safe next actions, so that I can recover without guessing.
3. As a household administrator, I want a 250-statement backfill supported, so that three years of history fit comfortably.
4. As a household administrator, I want review responsive for large statements, so that the CLI remains usable.
5. As a household administrator, I want clear installation and recovery instructions, so that I can operate the tool independently.
6. As a maintainer, I want every release gate automated where possible, so that regressions are caught consistently.

## Implementation Decisions

- Audit all terminal messages, logs, settings, cache artifacts, fixtures, and test snapshots for secrets and PII.
- Enforce owner-only permissions on credentials and retained cache files.
- Verify cleanup on success, cancellation, parse failure, review failure, Google failure, and interruption.
- Add safe, actionable recovery messaging for every defined failure class.
- Exercise 250 statements, 25,000 transactions, and a 1,000-transaction review model.
- Document setup, workbook configuration, routine import, backfill, cache retention/deletion, status, disconnect, and troubleshooting.
- Validate a real local sample from each institution without committing or copying it.
- Keep release tests deterministic; isolate opt-in live Google tests.

## Testing Decisions

- Run all PRD acceptance scenarios through the CLI seam.
- Add failure injection around filesystem, parser, review, Google read/write, and checkpoint operations.
- Scan tracked files for credential patterns, raw extracted text, full account numbers, and unintended PDFs.
- Measure discovery preview, backfill orchestration, fingerprint lookup, and review-model performance against PRD targets.
- Perform manual visual QA of the interactive table and Google Dashboard.
- Verify install/uninstall and credential disconnect on a clean macOS user environment.

## Out of Scope

- New features or institutions
- Product-scope expansion
- Performance work beyond stated household targets

## Further Notes

- Release only when all automated gates pass and the household administrator has manually accepted one sample per institution.
