# Family Spend Tracker

A privacy-conscious macOS CLI for importing AMEX, Bank of America, and Chase statement PDFs into a reviewed, categorized Google Sheets spending ledger.

The project is under active implementation. Phase 0 establishes the CLI, stable domain contracts, boundary ports, in-memory adapters, and acceptance-test harness.

## Development setup

Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
make check
```

The current command surface is available with:

```bash
.venv/bin/family-spend --help
```

## Project documents

- [Product requirements](docs/PRD.md)
- [Agent implementation plan](docs/specs/IMPLEMENTATION_PLAN.md)
- [Agent phase specifications](docs/specs/)
- [Phase 0 contracts](docs/architecture/phase-0-contracts.md)
- [Issue workflow](docs/agents/issue-tracker.md)

## Privacy

Do not commit real bank statements, extracted statement text, Google credentials, local caches, or full account/card numbers. Parser fixtures must be synthetic or irreversibly sanitized.
