# Contributing

## Branches and issues

- Select a `ready-for-agent` issue whose dependencies have merged.
- Use the canonical `dev/phase-*` branch named in that issue.
- Branch from the latest remote `main`.
- Never implement or push directly on `main`.
- Open a pull request into `main` and link the phase issue.

## Test seams

Use only the approved public seams:

1. The `family-spend` CLI is the primary acceptance seam.
2. Institution parsers use the shared parser contract.
3. Workbook adapters use the shared workbook gateway contract.

Tests assert public results and resulting boundary state. They do not assert private calls, helper structure, terminal rendering internals, or library-specific objects.

Development follows one red-green vertical slice at a time:

```bash
make check
```

## Sensitive data

Never commit:

- Real bank or credit-card statements
- Raw extracted statement text
- Google OAuth credentials or tokens
- Local caches or backfill checkpoints
- Full account or card numbers
- Test snapshots containing household data

Parser fixtures must be synthetic or irreversibly sanitized. Only masked account identifiers are permitted in source code, tests, fixtures, and logs.
