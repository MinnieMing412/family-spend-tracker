# Phase 2 - PDF Ingestion Framework and AMEX Parser

**Status:** Ready for agent
**Tracker label:** `ready-for-agent`
**Dependencies:** Phase 0

## Problem Statement

The CLI must safely distinguish processable statements from scanned, encrypted, corrupt, ambiguous, or unsupported PDFs and convert AMEX layouts into the common statement contract.

## Solution

Build recursive PDF discovery, validation, institution detection, parser dispatch, and the first production parser for AMEX. Use sanitized layout-preserving fixtures and exact expected normalized outputs.

## User Stories

1. As a household administrator, I want a PDF validated before parsing, so that unsupported files fail safely.
2. As a household administrator, I want AMEX detected automatically, so that I do not select a parser manually.
3. As a household administrator, I want AMEX purchases, credits, payments, fees, and interest typed correctly, so that spending rules work.
4. As a household administrator, I want AMEX cardholder sections preserved, so that member ownership can be assigned per transaction.
5. As a household administrator, I want statement totals extracted, so that the import can reconcile.
6. As a maintainer, I want sanitized fixtures, so that layout regressions are testable without household data.

## Implementation Decisions

- Validate PDF readability, encryption state, text presence, and page count before parser dispatch.
- Detect institutions using multiple stable statement markers, not filenames.
- Return explicit unsupported and ambiguous detection results.
- Parse AMEX statement identity, masked account identity, date range, closing date, cardholder sections, transaction rows, and reported section totals.
- Preserve posting-date markers and multi-line merchant/location information without leaking bank-specific shapes beyond parser metadata.
- Normalize signs according to the common transaction contract.
- Emit structured warnings for partial or ambiguous rows.
- Build synthetic or irreversibly sanitized AMEX fixtures based on observed layout features; do not commit the real sample.

## Testing Decisions

- Use parser contract tests with PDFs and expected normalized records.
- Cover purchases, merchant credits, payments, fees, interest, multiple cardholders, continuation pages, no-activity sections, and multi-line descriptions.
- Cover encrypted, scanned/image-only, corrupt, unsupported, and ambiguous PDFs.
- Assert exact decimal totals and transaction counts.
- Add CLI acceptance coverage for AMEX detection and parse-summary output using a fake workbook.

## Out of Scope

- Member alias resolution
- Categorization
- Interactive review
- Google writes
- BOA and Chase parsing

## Further Notes

- The parser returns evidence references suitable for review diagnostics but not full extracted statement text.
- Parser output must remain deterministic for the same PDF bytes.
