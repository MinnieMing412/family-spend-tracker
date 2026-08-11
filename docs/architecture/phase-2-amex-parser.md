# Phase 2 PDF Ingestion and AMEX Parser Architecture

## Boundaries

- `discover_pdfs` resolves one PDF or a recursive directory in deterministic
  relative-path order.
- `PdfValidator` hashes exact bytes, opens the PDF with `pypdf`, rejects
  encryption and invalid page structures, and extracts text one page at a time.
- `MarkerParserRegistry` selects an institution only when multiple stable
  content markers agree. It returns explicit detected, unsupported, or
  ambiguous results; filenames do not influence detection.
- `AmexStatementParser` converts the validated page text into the frozen common
  statement and transaction contracts.
- `StatementIngestionService` composes discovery, validation, detection, and
  parsing. Phase 2 exposes a parse summary but performs no workbook writes.

Raw extracted text remains inside the validated PDF/parser boundary. Evidence
references retain page and line coordinates, never full page text.

## Determinism and normalization

- The SHA-256 hash is computed from the exact source PDF bytes.
- Statement and transaction IDs derive from that hash and stable source-row
  coordinates, so repeated parsing of identical bytes returns identical IDs.
- AMEX purchases, fees, and interest are positive. Payments and merchant
  credits are negative. Payments are excluded from spend; merchant credits
  remain included so they reduce spend later.
- Cardholder labels, posting-date markers, statement sections, and evidence
  references are retained as source metadata without creating AMEX-specific
  domain fields.

## Test fixtures

The committed AMEX fixture is synthetic text with invented names, account
digits, dates, descriptions, and amounts. Tests render it into a minimal PDF so
the real validation and extraction path runs without committing a statement
binary. An expected JSON file freezes the normalized transaction and total
contract.

The fixture matrix covers:

- payments, credits, purchases, fees, and interest
- multiple cardholders and a continuation page
- a multi-line merchant/location row and posting marker
- a no-activity section and structured partial-row warning
- encrypted, image-only, corrupt, unsupported, and ambiguous PDFs
