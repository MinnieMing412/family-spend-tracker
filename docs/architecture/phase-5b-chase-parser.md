# Phase 5B Chase Parser Architecture

## Supported layout

`ChaseStatementParser` supports text-bearing Chase consumer credit-card
statements with an `Account Summary`, masked account number, opening/closing
dates, and `Account Activity` sections. Supported activity headings include
payments and other credits, purchases, cash advances, balance transfers, fees,
and interest.

Detection uses multiple content markers rather than filenames. A Chase document
without the supported account, period, or activity structure returns an explicit
`Unsupported Chase credit-card layout` diagnostic instead of a partial import.

## Encryption boundary

Some downloadable Chase PDFs use owner-permission encryption while requiring no
user password. `PdfValidator` now attempts only the empty password: when pypdf
confirms that it opens the document, normal text and corruption checks continue.
A non-empty user password is never requested or stored, and a PDF that does not
open with the empty password remains rejected as password-protected.

## Normalization and privacy

Account Summary values map to the shared payments/credits, new charges, cash
advances, balance transfers, fees, and interest reconciliation sections. Payment
and merchant-credit amounts are negative; purchases, fees, interest, and cash
advances are positive. Balance transfers are excluded from spending.

Stable IDs use the source hash and page/line evidence. Only the masked account
suffix is retained. Continuation lines such as marketplace order numbers are not
transaction rows, and long order/reference tokens embedded in merchant lines are
removed before normalized records leave the parser.

## Verification

The committed four-page fixture is synthetic. Contracts cover content-based
detection, exact normalized output, all summary totals, reconciliation,
deterministic IDs, partial-row warnings, unsupported layouts, identifier
filtering, owner-encrypted PDF acceptance, and password-locked PDF rejection.

CLI acceptance tests run Chase through the shared Phase 4 workflow and verify
parse-only detection, approval, unchanged re-import, parser-metadata stripping,
and cancellation without workbook writes. The production registry adds Chase
without a downstream review, duplicate, or workbook fork.
