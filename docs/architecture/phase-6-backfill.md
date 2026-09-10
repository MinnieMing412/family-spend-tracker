# Phase 6 Backfill Architecture

Phase 6 adds recursive historical folder processing without creating a second
import implementation. Each statement is prepared and committed through the
Phase 4 single-statement workflow.

## Planning and review

The command recursively discovers PDFs and presents the complete, deterministic
relative-path list before opening any document. After confirmation, supported
statements are prepared and ordered by detected closing date with path ordering
as the fallback. Parse failures remain deterministic plan entries.

The existing `ReviewState.is_clean` rule is the only bulk-approval criterion.
Clean states are summarized once and require an explicit confirmation. Before
each write, the statement is prepared again against current workbook state. A
statement that gained a duplicate or another exception after earlier commits is
routed to the ordinary individual reviewer instead of inheriting bulk approval.
Rejected files require an explicit skip decision before processing continues.

## Checkpoints and authority

Checkpoint JSON files live in the private application-support directory, not in
the repository. Their key is a SHA-256 identifier for the resolved root path;
their plan identity includes every relative path, file size, and modification
time. Owner-only filesystem permissions match the structured-cache policy.

Checkpoints are hints. On resume, a completed hash is skipped only when the
workbook has a matching complete import audit record. A stale checkpoint cannot
hide work that is missing from the workbook. Recorded rejected paths are reused
only when the plan identity still matches. Successful completion removes the
checkpoint.

## Execution and reporting

Writes remain sequential for deterministic rules, duplicate detection, and
auditing. A checkpoint follows every handled statement. The final summary reports
discovered, imported, duplicate, skipped, rejected, and unresolved counts. An
interrupted or declined run is explicitly marked incomplete.
