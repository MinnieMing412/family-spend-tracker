# Phase 0 - Foundation, Domain Contracts, and CLI Harness

**Status:** Ready for agent
**Tracker label:** `ready-for-agent`
**Dependencies:** None

## Problem Statement

The repository has requirements but no executable project, shared domain language, or test seam. Independent agents cannot safely build parsers, Google integration, or review workflows until stable contracts and a runnable CLI harness exist.

## Solution

Create the installable Python CLI skeleton, exact financial domain models, adapter interfaces, fake implementations, redacted error model, and the primary CLI acceptance-test harness. Freeze the normalized statement and transaction contracts that all later phases consume.

## User Stories

1. As a household administrator, I want a runnable `family-spend` command, so that later features have one consistent entry point.
2. As a maintainer, I want validated statement and transaction records, so that invalid financial data cannot cross module boundaries.
3. As a maintainer, I want exact decimal money handling, so that totals remain correct.
4. As a maintainer, I want adapters behind stable interfaces, so that core behavior can be tested without Google or a real terminal.
5. As a maintainer, I want an end-to-end CLI test harness, so that agents test user-visible outcomes.
6. As a household administrator, I want errors redacted, so that secrets and account numbers are not printed.

## Implementation Decisions

- Establish Python 3.12+ packaging, dependency management, linting, type checks, and tests.
- Create the `family-spend` entry point with placeholder subcommands from the PRD.
- Define normalized records for statements, transactions, warnings, reconciliation results, review state, workbook configuration, and import results.
- Define enums or constrained values for institution, transaction type, match type, import status, and warning severity.
- Define ports for parsers, workbook access, review, settings, checkpoints, caches, clock, and ID generation.
- Provide fake/in-memory adapters for acceptance tests.
- Centralize redaction and domain-to-CLI error translation.
- Add repository ignore rules for credentials, caches, temporary PDFs, extracted text, environment files, and platform artifacts.
- Add contributor guidance describing contract ownership and the real-statement prohibition.

## Testing Decisions

- Invoke the real CLI entry point in tests with fake adapters.
- Verify command discovery, help, exit codes, redacted failures, and isolated local state.
- Verify invalid amounts, dates, masked identifiers, and unsupported enum values are rejected.
- Verify decimal addition and sign conventions.
- Require every fake adapter to expose resulting state rather than call history.
- Do not snapshot full terminal markup.

## Out of Scope

- Real PDF parsing
- Google OAuth or API calls
- Interactive table rendering
- Import orchestration
- Dashboard creation

## Further Notes

- Downstream work starts only after normalized contracts and fake adapter behavior are documented and passing.
- Avoid institution-specific fields in the common transaction model unless stored as optional source metadata.
