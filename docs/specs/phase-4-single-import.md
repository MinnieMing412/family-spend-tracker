# Phase 4 - Single-Statement Import and Idempotent Commit

**Status:** Ready for agent
**Tracker label:** `ready-for-agent`
**Dependencies:** Phases 1, 2, and 3

## Problem Statement

The product components do not create value until one statement can travel safely from PDF through review into Google Sheets. Network retries and overlapping activity must not create duplicate or partially authoritative rows.

## Solution

Compose the existing adapters into the complete `family-spend import <pdf>` workflow. Add statement hashes, transaction fingerprints, near-duplicate detection, an idempotent workbook commit protocol, import audit records, and optional structured-cache retention.

## User Stories

1. As a household administrator, I want one command to process an AMEX statement end to end, so that monthly imports are practical.
2. As a household administrator, I want the same statement skipped on re-import, so that reruns are safe.
3. As a household administrator, I want exact duplicate rows skipped, so that overlaps do not inflate spending.
4. As a household administrator, I want near-duplicates reviewed, so that repeated legitimate purchases are preserved.
5. As a household administrator, I want failed writes retried safely, so that network errors do not duplicate rows.
6. As a household administrator, I want an import audit record, so that every row is traceable.
7. As a household administrator, I want cache data deleted by default or retained explicitly, so that privacy is under my control.

## Implementation Decisions

- Compute a cryptographic statement hash from original bytes.
- Compute transaction fingerprints from masked account identity, effective date, exact amount, normalized description, and deterministic occurrence discriminator.
- Compare against authoritative workbook import and transaction records before review.
- Present near-duplicates in review; never decide them solely by similarity.
- Commit stable transaction IDs and an import record as one logical operation using staged import status and idempotent retry checks.
- On retry, read existing stable IDs before appending.
- Upload only approved normalized fields and audit metadata, never raw extracted statement text.
- Delete temporary artifacts in a `finally`-equivalent path unless `--retain-cache` is set.
- Retained caches contain structured normalized data, diagnostics, fingerprints, and review decisions with owner-only permissions.

## Testing Decisions

- Make the AMEX end-to-end CLI scenario the primary acceptance test.
- Repeat the same command and assert unchanged workbook state.
- Simulate exact and near duplicates.
- Inject failures before write, after transaction write, and before final import status; assert retry converges to one completed import.
- Verify cancellation and validation failure write nothing.
- Verify default cleanup and retained-cache contents/permissions.
- Verify uploaded records contain no full account numbers or raw statement text.

## Out of Scope

- Recursive folder imports
- Backfill checkpoints
- BOA and Chase
- Dashboard charts

## Further Notes

- This phase is the first complete vertical slice and should be manually validated with the real AMEX sample without copying it into the repo.
