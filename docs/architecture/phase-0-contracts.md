# Phase 0 Contract Map

Phase 0 creates stable boundaries for later implementation phases. Domain logic does not import Google, terminal UI, PDF, or operating-system credential libraries.

## Primary seam

The `family-spend` CLI is the primary acceptance seam. Tests run the public command surface and assert exit status, redacted output, and resulting boundary state.

## Domain records

The normalized contract includes:

- Exact USD `Money`
- Supported institutions and transaction types
- Normalized transactions and statements
- Parser warnings and statement totals
- Reconciliation and review state
- Members, accounts, categories, and merchant rules
- Local connection settings
- Import records and results
- Backfill checkpoints and structured-cache records

Bank-specific parsers map their source labels into these common records. They must not introduce institution-specific transaction shapes downstream.

## Ports

- `StatementParser` converts one validated PDF into a parse result.
- `ParserRegistry` selects one parser for a validated PDF.
- `WorkbookGateway` owns authoritative workbook reads and idempotent import commits.
- `ReviewPort` obtains an explicit approved, corrected, or cancelled review state.
- `SettingsStore` owns the local workbook and credential reference.
- `CheckpointStore` owns resumable backfill progress.
- `StructuredCache` owns optional structured parser artifacts.
- `Clock` and `IdGenerator` make time and identifiers deterministic in tests.

## Test adapters

In-memory settings, workbook, checkpoint, and structured-cache adapters expose final state through their public ports. Static parser/registry adapters, a scripted review port, a fixed clock, and a sequential ID generator support CLI acceptance tests without network access or real statements.

## Error boundary

Domain and adapter failures become actionable CLI messages at the outer boundary. Redaction removes OAuth-style tokens and email addresses and masks long account/card numbers to their final four digits.
