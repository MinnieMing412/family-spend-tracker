# Phase 3 Review and Rules Architecture

## Review snapshot

`ReviewState` remains the stable `ReviewPort` boundary. Each `ReviewRow` keeps:

- the original normalized parser transaction
- the current corrected transaction
- structured warnings
- exact, near, or no duplicate state
- exact-rule, contains-rule, manual, uncategorized, or not-applicable category source

Clean status is a computed domain property. A review cannot be approved while
ownership or a spending category is unresolved, a near-duplicate remains,
warning/error evidence remains, or reconciliation is neither matched nor
explicitly overridden.

## Enrichment order

1. Match an active member by normalized cardholder alias.
2. If no alias resolves, use the active configured account's active default member.
3. Normalize merchant text independently from category lookup.
4. Apply active exact merchant rules before all contains rules.
5. Within each rule kind, sort by descending priority and stable rule ID.
6. Mark unmatched spending as `uncategorized`; non-spending types have no category.
7. Derive `included_in_spend` exclusively from transaction type.

Manual category corrections may produce a deterministic rule decision returned
with the review snapshot. Phase 4 owns committing those rules and transactions.

## Reconciliation

Supported statement totals are reconciled independently for payments, merchant
credits, new charges, fees, and interest. Cardholder-specific new-charge totals
use retained parser metadata. All arithmetic uses `Decimal`; a difference no
larger than USD 0.01 is matched.

Only a discrepancy can be overridden, and the override requires a non-empty
reason retained on the reconciliation result. Missing supported totals remain
unavailable and block clean approval.

## Terminal boundary

`TerminalReviewPort` is a line-oriented, dependency-free adapter. It renders a
table with textual flags so accessibility does not depend on color. Commands
support all/exception filters, field edits, bulk category assignment, merchant
rule decisions, near-duplicate resolution, reconciliation overrides, explicit
approval, and cancellation.

Acceptance tests use scripted `ReviewPort` implementations and assert final
state rather than terminal keystroke internals. Cancellation returns before any
workbook commit boundary is called.
