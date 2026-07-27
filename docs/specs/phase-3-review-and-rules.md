# Phase 3 - Categorization, Reconciliation, and Interactive Review

**Status:** Ready for agent
**Tracker label:** `ready-for-agent`
**Dependencies:** Phase 0 and the normalized fixture contract from Phase 2

## Problem Statement

Parsed transactions are not safe to upload until ownership, categorization, reconciliation, and duplicate ambiguity are visible and correctable. A slow prompt-per-field workflow would make routine imports and backfill impractical.

## Solution

Implement deterministic enrichment and clean-status logic, then expose it through an interactive terminal table with filters, edits, bulk category assignment, merchant-rule creation, cancellation, and explicit approval.

## User Stories

1. As a household administrator, I want aliases matched to members, so that transactions are attributed correctly.
2. As a household administrator, I want unknown owners flagged, so that the CLI never guesses silently.
3. As a household administrator, I want merchant descriptions normalized, so that recurring merchants match consistently.
4. As a household administrator, I want exact rules applied before broader rules, so that categorization is deterministic.
5. As a household administrator, I want unresolved spending marked `Uncategorized`, so that it remains visible.
6. As a household administrator, I want statement sections reconciled, so that parser omissions are caught.
7. As a household administrator, I want an interactive table with exception filters and bulk edits, so that review is efficient.
8. As a household administrator, I want cancellation to preserve workbook state, so that incomplete review uploads nothing.

## Implementation Decisions

- Resolve member aliases first and configured account ownership second; otherwise require review.
- Normalize merchants separately from categorization so normalization rules can be tested independently.
- Apply merchant rules by deterministic priority: approved exact mappings before ordered broader patterns.
- Compute `included in spend` from transaction type, never from category.
- Reconcile available statement sections independently with exact decimals and a USD 0.01 tolerance.
- Compute clean status in domain logic from all warnings and unresolved states.
- Model review edits as explicit decisions over a review snapshot.
- Allow edits to member, merchant, date, amount, type, and category.
- Offer a rule-save decision after merchant/category correction.
- Require a non-empty reason for reconciliation override.
- Keep terminal rendering behind `ReviewPort` so scripted acceptance tests remain stable.

## Testing Decisions

- Test ownership resolution, merchant normalization, rule precedence, spending inclusion, reconciliation, and clean-status behavior as observable transformations.
- Test the CLI using scripted review decisions rather than keystroke-level terminal tests.
- Verify cancel produces no approved import.
- Verify bulk edits affect only selected rows.
- Verify saved rules influence the next simulated statement.
- Verify uncategorized, ambiguous, near-duplicate, and unreconciled rows prevent clean status.

## Out of Scope

- Google commit behavior
- Statement hashing
- Backfill bulk approval
- Additional institution parsers

## Further Notes

- The interactive implementation may use a terminal UI library, but tests must depend only on `ReviewPort`.
- Accessibility should not rely on color alone; warnings also need text or symbols.
