# Phase 5A - Bank of America Parser

**Status:** Ready for agent
**Tracker label:** `ready-for-agent`
**Implementation branch:** `dev/phase-5a-boa-parser`
**Dependencies:** Phase 2 parser contract and Phase 4 import contract

## Problem Statement

Bank of America statements must enter the same ledger without institution-specific logic leaking into review, categorization, duplicate, or workbook modules.

## Solution

Add Bank of America detection markers and one or more layout parsers conforming to the existing parser contract. Supply sanitized fixtures and run the shared import acceptance suite.

## User Stories

1. As a household administrator, I want Bank of America statements detected automatically, so that they use the correct parser.
2. As a household administrator, I want all statement activity normalized, so that BOA totals and analysis are accurate.
3. As a household administrator, I want account ownership resolved through existing workbook rules, so that BOA does not require a separate workflow.
4. As a maintainer, I want BOA variants isolated behind the parser contract, so that later layout changes are maintainable.

## Implementation Decisions

- Reuse common PDF validation, models, warnings, sign conventions, and parser registry.
- Detect BOA from content rather than filename.
- Extract all common identity, transaction, section-total, and account/cardholder fields available in the supported layouts.
- Add format-version dispatch only when materially distinct layouts require it.
- Do not change common domain contracts solely to mirror BOA labels; map them to existing concepts.

## Testing Decisions

- Build sanitized BOA fixtures covering representative accounts and continuation pages.
- Run the shared parser contract and full single-import CLI acceptance scenarios.
- Verify exact section reconciliation, transaction typing, description normalization inputs, and masked account handling.
- Add explicit unsupported-layout diagnostics for layouts not represented.

## Out of Scope

- Chase parsing
- Changes to Google, review, dashboard, or backfill behavior

## Further Notes

- The agent needs representative BOA samples locally before declaring the phase complete.
