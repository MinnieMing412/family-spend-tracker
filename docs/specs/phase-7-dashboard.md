# Phase 7 - Google Sheets Dashboard and Analytics

**Status:** Ready for agent
**Tracker label:** `ready-for-agent`
**Implementation branch:** `dev/phase-7-dashboard`
**Dependencies:** Phase 1 and the stable approved transaction schema from Phase 4

## Problem Statement

A normalized transaction ledger is not enough; the household needs automatically updated category, monthly, merchant, and member insights with consistent spend accounting.

## Solution

Provision a filterable Google Sheets Dashboard derived from approved transaction rows. Implement the finalized spend rules once in chart-support data and create summary cards, category bars, monthly columns, member comparison, category-by-month values, and top-merchant rankings.

## User Stories

1. As a household administrator, I want a trailing-12-month default view, so that recent trends are immediately useful.
2. As a household administrator, I want date, member, account, and category controls, so that I can focus the analysis.
3. As a household administrator, I want net spending by category, so that I can see where money goes.
4. As a household administrator, I want monthly trends, so that spikes and seasonality are visible.
5. As a household administrator, I want member comparisons, so that household patterns are understandable.
6. As a household administrator, I want top merchants and uncategorized counts, so that large and incomplete areas are visible.
7. As a household administrator, I want direct transaction edits reflected, so that the sheet remains authoritative.

## Implementation Decisions

- Derive all analytics from approved `Transactions` rows.
- Centralize included-spend logic so every chart follows the same rules.
- Net merchant credits against their assigned categories.
- Include fees; exclude payments, transfers, rewards, and interest from main spend.
- Include and flag cash advances.
- Permit negative category totals.
- Default controls to trailing 12 months and `All` dimensions.
- Use a horizontal descending category bar chart, monthly total columns, and grouped or stacked member columns.
- Keep top merchants as a ranked table.
- Keep chart-support tables visible or inspectable enough for audit.
- Provision/update dashboard structures idempotently without replacing user transaction data.

## Testing Decisions

- Seed a disposable workbook with controlled approved and unapproved rows.
- Assert support-table values for every transaction type and a refund-exceeds-purchase case.
- Verify filters change computed values.
- Verify direct transaction edits are reflected.
- Verify repeated provisioning does not duplicate charts or controls.
- Inspect chart metadata in integration tests and include a manual visual QA checklist.

## Out of Scope

- Local reports
- Forecasting, budgets, or alerts
- Tax views
- New transaction categories beyond workbook configuration

## Further Notes

- Google Sheets chart rendering needs manual visual verification in addition to metadata assertions.
