# Phase 6 - Folder Import and Resumable Backfill

**Status:** Ready for agent
**Tracker label:** `ready-for-agent`
**Implementation branch:** `dev/phase-6-backfill`
**Dependencies:** Phase 4; Phases 5A and 5B required before v1 release

## Problem Statement

The household has roughly 150-220 historical PDFs. Processing each with an isolated command is inefficient, while a monolithic run would be fragile and force unnecessary review of clean statements.

## Solution

Build recursive discovery, chronological planning, preview, checkpoint/resume, clean-statement bulk approval, individual exception review, and final summaries by repeatedly invoking the proven single-statement pipeline.

## User Stories

1. As a household administrator, I want PDFs discovered recursively, so that my year/month folders can be used directly.
2. As a household administrator, I want a complete preview, so that I know the scope before parsing.
3. As a household administrator, I want chronological processing, so that historical rules and audit records are understandable.
4. As a household administrator, I want checkpoints after every statement, so that interruption loses minimal work.
5. As a household administrator, I want `--resume`, so that a backfill can continue safely.
6. As a household administrator, I want clean statements bulk-approved, so that backfill is efficient.
7. As a household administrator, I want exceptions reviewed individually, so that efficiency does not compromise accuracy.
8. As a household administrator, I want a final status summary, so that unresolved files are actionable.

## Implementation Decisions

- Reuse the single-statement pipeline; do not fork parsing, categorization, duplicate, review, or commit logic.
- Separate cheap discovery/preview from full parsing.
- Sort by detected statement date when available, with deterministic path ordering as fallback.
- Store checkpoints outside the repository and bind them to the backfill root and plan identity.
- Treat authoritative workbook imports as the final proof of completion; checkpoints are resumability hints.
- Compute clean status using the Phase 3 domain rule.
- Present one summary for clean candidates and require explicit bulk approval.
- Route every exception through individual review or an explicit skip decision.
- Continue past rejected files only after recording their status.

## Testing Decisions

- Test discovery on nested directories, mixed file types, duplicate paths, and unreadable files.
- Interrupt after controlled statements and assert `--resume` processes only remaining work.
- Verify stale checkpoints reconcile with workbook state.
- Verify clean bulk approval cannot include exception statements.
- Verify rejected, skipped, imported, duplicate, and unresolved counts.
- Run a synthetic 250-statement plan and assert checkpoint and preview performance targets.

## Out of Scope

- New parser behavior
- Dashboard implementation
- Concurrent Google writes

## Further Notes

- Sequential statement commits are preferred for auditability. Parsing may be optimized later only if deterministic ordering and privacy remain intact.
