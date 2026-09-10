# Phase 7 Dashboard Architecture

Phase 7 provisions a formula-driven Google Sheets Dashboard from the approved
`Transactions` ledger. The Dashboard is derived output and never becomes an
authoritative transaction store.

## Spend and filter model

The shared `included_in_spend` predicate owns the finalized spending rule:
purchases, merchant credits, fees, and cash advances are included. Payments,
transfers, rewards, interest, and other activity remain in the ledger but are
excluded from main spend. Credits retain their negative amount, so a category
may have a negative total. Cash advances have an explicit support flag and count.

An inspectable helper table on `Dashboard` references transaction rows with
array formulas. It converts ISO dates and decimal strings to native Sheet values,
requires the reviewed flag, suppresses repeated fingerprints, evaluates spend
eligibility once, and applies the date, member, institution, account, and category
controls once. Every summary and chart-support table reads the resulting
in-view net-spend column.

The default date controls cover the trailing 12 months through today. Dimension
controls default to `All` and use validated lists backed by active workbook
configuration. Formula ranges have capacity for the release target of 25,000
transactions. Direct edits to transaction dates, amounts, types, ownership,
accounts, categories, merchants, and review flags automatically recalculate the
derived view.

## Output and provisioning

The opening view contains total net spend, average monthly spend, largest
category, uncategorized count, cash-advance count, and a ranked top-merchants
table. Native charts provide descending category bars, monthly columns, and
member-by-month columns. The category-by-month matrix and all chart source ranges
remain inspectable in the support area.

Provisioning clears and replaces only the derived Dashboard sheet. It preserves
all ledger and configuration sheets, removes existing embedded dashboard charts,
and recreates three charts, controls, formulas, validation, and formatting. This
makes repeated setup or dashboard provisioning idempotent.

## Manual Google Sheets visual QA checklist

- Open Dashboard at normal zoom and confirm the title, controls, cards, tables,
  and charts are legible without clipped labels or values.
- Confirm the three charts do not overlap controls, cards, or the support-table
  header at row 55.
- Confirm the category chart is horizontal and descending, the monthly chart is
  chronological, and the member chart has one distinguishable series per member.
- Change each control and verify all cards, tables, and charts update together.
- Edit an approved transaction amount, category, merchant, member, and type; then
  confirm recalculation without rerunning the CLI.
- Add a refund larger than its category purchases and confirm the negative total
  remains visible.
- Add a cash advance and confirm it contributes to spend and to the cash-advance
  count.
- Run setup/provisioning again and confirm there are still exactly three charts
  and one set of controls.
