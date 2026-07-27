# Phase 5B - Chase Parser

**Status:** Ready for agent
**Tracker label:** `ready-for-agent`
**Dependencies:** Phase 2 parser contract and Phase 4 import contract

## Problem Statement

Chase statements must enter the common ledger and workflow without adding Chase-specific behavior to downstream modules.

## Solution

Add Chase detection markers and layout parsers conforming to the normalized statement contract. Supply sanitized fixtures and run the shared parser and import acceptance suites.

## User Stories

1. As a household administrator, I want Chase statements detected automatically, so that they use the correct parser.
2. As a household administrator, I want purchases, credits, payments, fees, interest, and available cardholder detail normalized, so that Chase activity is accurate.
3. As a household administrator, I want existing ownership and merchant rules applied to Chase transactions, so that all institutions share one review workflow.
4. As a maintainer, I want Chase layout variants isolated, so that parser maintenance does not destabilize imports.

## Implementation Decisions

- Reuse common PDF validation, models, warnings, sign conventions, and parser registry.
- Detect Chase from statement content rather than filenames.
- Extract all available common identity, transaction, section-total, and cardholder fields.
- Map Chase-specific labels and signs into common transaction types.
- Keep layout-version handling inside the Chase adapter.

## Testing Decisions

- Build sanitized Chase fixtures covering representative layouts and continuation pages.
- Run the shared parser contract and full single-import CLI acceptance scenarios.
- Verify exact reconciliation, transaction typing, masked identifiers, and deterministic output.
- Verify unsupported variants fail clearly rather than partially parsing.

## Out of Scope

- Bank of America parsing
- Changes to Google, review, dashboard, or backfill behavior

## Further Notes

- The agent needs representative Chase samples locally before declaring the phase complete.
