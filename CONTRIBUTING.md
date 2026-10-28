# Contributing

This repository is a solo ExaThon India 2026 entry. The same rules apply if you fork it.

## Rules we will not break

- **Exasol Personal** is the data platform. Matching, classification, root-cause grouping, and the audit trail run as SQL inside Exasol.
- **Synthetic or public data only.** No employer data, no real UPI payloads, no customer PII.
- **MIT licence** stays on every distribution.
- **No secrets in git.** Copy `.env.example` to `.env`.

## How to work

```bash
make setup
make test
```

Core logic lives in `sql/`. Python in `closedesk/` generates data, loads it, runs the SQL stages, and serves the UI.

The explanation agent must still run with `LLM_PROVIDER=none`.

## Pull requests

Not expected during the challenge window. After 31 Oct 2026, open an issue first.
