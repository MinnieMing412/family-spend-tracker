# Phase 5A Bank of America Parser Architecture

## Supported layout

`BankOfAmericaStatementParser` dispatches between text-bearing Bank of America
consumer credit-card and deposit-account layouts.

The credit-card adapter supports these content features:

- a masked or full account-number label from which only the final four digits
  are retained
- a numeric billing cycle and optional statement-closing date
- account-summary totals for payments and other credits, purchases and
  adjustments, fees, and interest
- transaction and posting dates followed by a description and amount
- optional transaction reference and row-level account suffixes
- transaction sections for payments/credits, purchases, balance transfers,
  cash advances, fees, and interest
- section and cardholder headers repeated on continuation pages

Detection uses content markers, never the filename. A document that matches BOA
markers but lacks the supported account, billing-cycle, or transaction structure
returns an explicit `Unsupported Bank of America credit-card layout` error.

The deposit adapter supports an Advantage Banking-style statement period,
account summary, deposits and other additions, withdrawals and other
subtractions, checks, service fees, and transaction tables. It tolerates PDF text
extraction that concatenates a whole transaction page into one text run.

## Normalization

BOA activity maps directly into the common transaction contract. Payments and
merchant credits are negative; purchases, fees, interest, and cash advances are
positive. Balance transfers use the common non-spending `transfer` type. The
combined `Payments and Other Credits` reported total reconciles against both
payment and merchant-credit rows, while the other summary totals reuse the same
reconciliation sections as AMEX.

Deposit inflows and account transfers are excluded from spending. Credit-card
autopay and ACH payment rows become payments, transfers remain transfers, and
debit-card/check-card purchases become positive purchases included in spend.
Deposit-statement reconciliation uses the original signed statement amount kept
in parser-only metadata, so workbook analytics retain the common spending sign
convention without weakening cash-flow reconciliation.

Stable statement and transaction IDs use the source SHA-256 and evidence
position. Transaction metadata retains page/line evidence, the masked row account,
an optional normalized cardholder alias, and only the last six characters of a
reference number. Full account and reference numbers are never copied into the
normalized statement.

## Verification

The committed fixtures are entirely synthetic and span both supported layouts. Contract tests
cover content detection, unsupported layouts, exact records and totals,
reconciliation, multiline descriptions, continuation metadata, stable IDs,
partial-row warnings, balance transfers, cash advances, compressed deposit-page
extraction, deposit typing, and identifier masking.

CLI acceptance tests pass the fixture through the shared Phase 4 workflow. They
verify parse-only detection, approved import, unchanged re-import, cache cleanup,
and cancellation without workbook writes. The production parser registry includes
both AMEX and BOA registrations; no workbook, review, duplicate, or commit fork is
introduced.

## Known boundary

Materially different BOA layouts are not inferred from these parsers. They remain
unsupported until a representative, sanitized sample can establish a separate
format adapter and fixture.
