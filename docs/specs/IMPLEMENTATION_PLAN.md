# Family Spend Tracker - Agent Implementation Plan

**Status:** Ready for agent execution
**Tracker label:** `ready-for-agent`
**Source:** `docs/PRD.md`

## Problem Statement

A household administrator has three years of spending spread across AMEX, Bank of America, and Chase statement PDFs for two people and multiple accounts. Manual spreadsheet entry is slow, inconsistent, and prone to duplicate transactions. The administrator needs a private, review-first CLI that turns supported statements into an authoritative Google Sheets ledger and useful spending charts.

The repository currently contains the finalized product requirements but no implementation. Work must therefore establish a stable domain contract and an end-to-end test seam before institution parsers, Google integration, review behavior, and backfill can be developed safely by different agents.

## Solution

Build a macOS-oriented Python CLI with a pure domain pipeline surrounded by replaceable adapters:

- PDF source and institution parser adapters
- Google OAuth and workbook gateway adapters
- Interactive terminal review adapter
- Local settings, checkpoint, and structured-cache adapters

The primary executable seam is the CLI itself. Automated acceptance tests will invoke CLI commands with sanitized PDF fixtures, a fake workbook gateway, and scripted review decisions, then assert terminal output, exit status, workbook state, retained cache state, and idempotent retry behavior.

Implementation is divided into dependency-aware phases. Every phase delivers externally testable behavior and stable contracts for downstream agents. AMEX provides the first vertical slice; Bank of America and Chase follow as parallel parser work after the parser contract is proven.

## User Stories

1. As a household administrator, I want to initialize the CLI, so that I can use a supported and repeatable local setup.
2. As a household administrator, I want browser-based Google authorization, so that I do not store my Google password in the application.
3. As a household administrator, I want the smallest necessary Google permissions requested, so that access is limited to the product's needs.
4. As a household administrator, I want to create a compatible workbook automatically, so that setup requires minimal spreadsheet work.
5. As a household administrator, I want to connect an existing compatible workbook, so that I can control where household data lives.
6. As a household administrator, I want workbook compatibility validated, so that an import cannot corrupt an incompatible sheet.
7. As a household administrator, I want members and statement aliases stored in the workbook, so that ownership mappings remain editable.
8. As a household administrator, I want accounts and masked identifiers stored in the workbook, so that transactions can be assigned without retaining full card numbers.
9. As a household administrator, I want categories stored in the workbook, so that the taxonomy can evolve without a software release.
10. As a household administrator, I want merchant rules stored in the workbook, so that approved categorization decisions are reused.
11. As a household administrator, I want to import one statement PDF, so that routine monthly updates are simple.
12. As a household administrator, I want to import a directory recursively, so that year/month statement folders need no reorganization.
13. As a household administrator, I want the detected file list previewed, so that I know what will be processed.
14. As a household administrator, I want AMEX statements detected and parsed, so that AMEX activity enters the common ledger.
15. As a household administrator, I want Bank of America statements detected and parsed, so that Bank of America activity enters the common ledger.
16. As a household administrator, I want Chase statements detected and parsed, so that Chase activity enters the common ledger.
17. As a household administrator, I want unsupported, scanned, corrupt, or encrypted PDFs rejected clearly, so that failures are safe and actionable.
18. As a household administrator, I want every amount represented exactly, so that financial totals do not drift.
19. As a household administrator, I want transactions normalized across banks, so that the workbook has one consistent schema.
20. As a household administrator, I want transaction ownership assigned per cardholder when available, so that family-member analysis is accurate.
21. As a household administrator, I want ambiguous ownership flagged, so that the CLI never silently attributes spending to the wrong person.
22. As a household administrator, I want known merchants categorized consistently, so that recurring purchases require less review.
23. As a household administrator, I want unknown merchants visibly uncategorized, so that missing categorization cannot hide spending.
24. As a household administrator, I want to save approved merchant rules during review, so that later imports improve deterministically.
25. As a household administrator, I want no transaction descriptions sent to an AI service, so that categorization remains private.
26. As a household administrator, I want extracted totals reconciled with statement totals, so that parser omissions are detected.
27. As a household administrator, I want reconciliation overrides to require a reason, so that discrepancies remain auditable.
28. As a household administrator, I want an interactive transaction table, so that I can review statements efficiently.
29. As a household administrator, I want uncertain rows highlighted and filterable, so that I can focus on required decisions.
30. As a household administrator, I want bulk merchant/category edits, so that repeated unknown merchants are quick to resolve.
31. As a household administrator, I want cancelling review to upload nothing, so that incomplete work does not enter the ledger.
32. As a household administrator, I want duplicate statements skipped, so that rerunning a command is safe.
33. As a household administrator, I want exact duplicate transactions skipped, so that overlapping statements do not inflate spending.
34. As a household administrator, I want near-duplicates flagged, so that legitimate repeated purchases are not discarded silently.
35. As a household administrator, I want retries to be idempotent, so that network failures do not create duplicate rows.
36. As a household administrator, I want a resumable historical backfill, so that three years of statements can be loaded over multiple sessions.
37. As a household administrator, I want clean historical statements bulk-approved, so that backfill does not require unnecessary prompts.
38. As a household administrator, I want exception statements reviewed individually, so that bulk operation does not reduce accuracy.
39. As a household administrator, I want progress checkpointed after each statement, so that interruption loses minimal work.
40. As a household administrator, I want the dashboard to default to the trailing 12 months, so that recent trends are immediately visible.
41. As a household administrator, I want category spending, monthly trends, and member comparisons, so that I can understand household spending patterns.
42. As a household administrator, I want dashboard filters, so that I can focus on a date range, person, account, or category.
43. As a household administrator, I want refunds to reduce category spend and payments excluded, so that analysis measures actual spending.
44. As a household administrator, I want temporary parser data deleted by default, so that sensitive local data does not accumulate.
45. As a household administrator, I want optional structured audit-cache retention, so that I can diagnose selected imports.
46. As a household administrator, I want credentials and caches outside Git, so that sensitive material cannot be committed accidentally.
47. As a household administrator, I want a status command, so that I can see the active workbook and unresolved work safely.
48. As a household administrator, I want to disconnect and remove local credentials, so that I can revoke local access.
49. As a maintainer, I want sanitized parser fixtures, so that bank layouts can be regression-tested without real household data.
50. As a maintainer, I want deterministic behavior at stable boundaries, so that multiple agents can extend the product safely.

## Implementation Decisions

### Architecture

- Use Python 3.12 or newer with a conventional installable package and a `family-spend` console entry point.
- Keep financial and workflow logic independent of terminal, Google, PDF-library, and filesystem implementations.
- Represent money with decimal values and dates with explicit date types.
- Use immutable or validation-enforced domain records at adapter boundaries.
- Define logical components for:
  - CLI command orchestration
  - Statement discovery and validation
  - Institution detection and parser dispatch
  - Normalized statement and transaction models
  - Member/account resolution
  - Merchant normalization and categorization
  - Reconciliation
  - Duplicate detection and fingerprints
  - Review sessions
  - Workbook gateway
  - Google OAuth
  - Local settings, checkpoint, and cache storage
  - Dashboard provisioning
- Return structured domain errors from core logic and translate them to redacted, actionable CLI messages at the outer boundary.

### Stable interfaces

- `StatementParser`: accepts a validated PDF source and returns a normalized statement plus warnings and source evidence references.
- `ParserRegistry`: detects one supported institution/format or returns an explicit unsupported/ambiguous result.
- `WorkbookGateway`: reads authoritative configuration and ledger state, validates/provisions the schema, and commits an approved import idempotently.
- `ReviewPort`: accepts a review model and returns approve, cancel, or corrected review decisions.
- `SettingsStore`: manages workbook identity and credential references without exposing secret material to domain logic.
- `CheckpointStore`: records backfill progress independently of uploaded ledger state.
- `StructuredCache`: optionally retains redacted normalized parser and review artifacts.
- The normalized statement contract is frozen at the end of Phase 0; later parser agents must conform to it rather than create bank-specific transaction shapes.

### Source-of-truth rules

- Google Sheets is authoritative for members, accounts, categories, merchant rules, approved transactions, and import history.
- Local state is authoritative only for OAuth material, connected workbook identity, in-progress backfill checkpoints, and optional structured caches.
- Direct edits to approved transaction rows are respected on later imports.
- Dashboard tables and charts are derived views, never authoritative data.

### Agent phases

| Phase | Agent brief | Depends on | Parallelism | Exit outcome |
|---|---|---|---|---|
| 0 | Foundation, domain contracts, CLI harness | None | Starts first | Installable CLI, pure domain models, fake adapters, end-to-end test harness |
| 1 | Google workbook and OAuth foundation | 0 | Parallel with 2 | Setup/connect/validate/status/disconnect against workbook gateway |
| 2 | PDF ingestion framework and AMEX parser | 0 | Parallel with 1 | Validated PDF intake and normalized AMEX statement parsing |
| 3 | Categorization, reconciliation, and interactive review | 0 and normalized fixtures from 2 | After parser contract; may overlap late Phase 2 | Reviewable and correctable statement model |
| 4 | Single-statement import and idempotent commit | 1, 2, 3 | Integration phase | Complete AMEX import vertical slice |
| 5A | Bank of America parser | 2 and Phase 4 contract | Parallel with 5B and dashboard work | BOA fixtures pass common parser contract |
| 5B | Chase parser | 2 and Phase 4 contract | Parallel with 5A and dashboard work | Chase fixtures pass common parser contract |
| 6 | Folder import and resumable backfill | 4, with 5A/5B before release | Parallel with 7 after contracts settle | Recursive, checkpointed, bulk-approval workflow |
| 7 | Dashboard and workbook analytics | 1 and stable transaction schema from 4 | Parallel with 5A/5B/6 | Filterable trailing-12-month Google dashboard |
| 8 | Privacy, failure recovery, performance, and release hardening | 5A, 5B, 6, 7 | Final integration | Release gates and full acceptance suite pass |

### Phase ownership rules

- An agent changes only the contracts owned by its phase unless the owning phase agent agrees.
- Contract changes require updating fake adapters and the CLI acceptance harness in the same change.
- Institution parser agents do not modify Google or review behavior.
- Dashboard work consumes the approved transaction schema and does not redefine spending rules.
- Backfill work invokes the same single-statement pipeline; it does not create a second import implementation.

### Review and approval

- The review domain model contains the original parsed value, current corrected value, warnings, duplicate state, categorization source, and reconciliation summary.
- A statement cannot be classified clean if it is unreconciled, uncategorized, ambiguously owned, near-duplicate, or otherwise warned.
- Clean status is computed by domain logic and cannot be asserted by an adapter.
- A reconciliation override records the amount difference and a non-empty reason.

### Import commit protocol

- Statement hashes provide coarse duplicate prevention.
- Transaction fingerprints provide row-level duplicate prevention.
- The workbook adapter uses a staged import status and stable IDs so retry can determine whether a previous write completed.
- An approved import writes transaction rows and its import audit record as one logical operation.
- A failed retry reads existing stable IDs before adding rows.

### Fixture policy

- Never commit the supplied real AMEX statement.
- Build synthetic or irreversibly sanitized fixtures that retain layout features required by each parser.
- Every parser fixture includes expected normalized output and reconciliation totals.
- Fixture review includes a check that names, account digits, addresses, phone numbers, and real transaction details are absent.

## Testing Decisions

### Primary test seam

The highest and preferred seam is a CLI acceptance harness. It runs commands with:

- Sanitized PDF fixtures
- A deterministic fake workbook gateway
- A scripted review port
- Isolated settings, checkpoints, and cache locations

Tests assert only observable behavior:

- Exit status
- Redacted terminal output
- Final fake workbook records
- Import/checkpoint/cache artifacts
- Safe behavior when a command is repeated

Tests must not assert private helper calls, library-specific objects, internal class counts, or terminal rendering implementation.

### Secondary seams

Only two narrower seams are justified:

1. Parser contract tests because bank layouts vary independently and failures need fixture-level diagnosis.
2. Workbook adapter contract tests because Google API batching, retries, and schema operations cannot be proven by the fake gateway.

Every workbook gateway implementation, including the fake, must pass the same behavioral contract suite where applicable.

### Test coverage by phase

- Phase 0: CLI lifecycle, domain validation, decimal behavior, error redaction, fake adapter contracts.
- Phase 1: workbook creation/validation, schema compatibility, auth lifecycle, minimum-scope configuration, adapter retry behavior.
- Phase 2: PDF rejection cases, institution detection, AMEX variants, multi-cardholder parsing, exact section totals.
- Phase 3: rule precedence, normalization, ownership resolution, reconciliation, clean-status computation, review corrections/cancel.
- Phase 4: complete import, duplicate statement, duplicate transaction, near-duplicate decision, partial-write retry.
- Phase 5A/5B: institution fixture matrices and normalized-output equivalence.
- Phase 6: discovery ordering, checkpoint/resume, clean bulk approval, exception isolation, interrupted runs.
- Phase 7: workbook formulas/pivots/charts and spend-rule results from controlled ledger rows.
- Phase 8: redaction, cache deletion/retention, permission checks, 250-statement and 25,000-transaction performance runs, full acceptance suite.

### Quality bar

- Tests describe user-observable outcomes.
- Financial assertions use exact expected decimals.
- Time-dependent behavior uses an injected clock.
- Stable IDs and hashes use deterministic fixture inputs.
- Network tests are isolated from default unit/acceptance runs.
- Real Google tests use a disposable workbook and clean it up explicitly.
- No test records secrets or real household data in snapshots or logs.

## Out of Scope

- Live bank APIs
- OCR and encrypted PDFs
- Additional institutions, languages, and currencies
- Budgets, alerts, forecasting, receipts, tax features, and split transactions
- AI categorization
- Multi-user CLI operation
- Web/mobile UI
- Local analytical reports
- Redesigning the finalized product requirements

## Further Notes

- Product requirements remain authoritative in `docs/PRD.md`.
- Phase briefs in this directory are intended to become separate issue-tracker items with the `ready-for-agent` label.
- The repository has no configured remote or issue-tracker instructions at the time of synthesis, so issue publication must wait until a tracker is connected.
- The real AMEX sample may be used locally for manual verification but must never be copied into the repository, committed, or exposed in logs.
