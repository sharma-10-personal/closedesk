# CloseDesk

**ExaThon India 2026 · Track: Money, Risk & Regulation**

A payments-operations analyst at a mid-size bank can't close the day's UPI reconciliation, because the settlement file, the core-banking ledger and the merchant records disagree on thousands of transactions, and she traces each one by hand across spreadsheets. If this worked, she'd start the day with a short list of true exceptions, each with a cause, the rupees at risk and a proposed fix she can approve in one click.

CloseDesk matches those three lists in **Exasol Personal**, groups leftovers by root cause, ranks them by rupees at risk, and lets an agent *propose* a fix. A human must approve every change. Nothing posts to the books without that click.

> All payment rows in this project are **synthetic**. There is no real UPI, customer, or employer data. See [docs/data-sources.md](docs/data-sources.md).

## Status

Scaffold only. Measured results will go in [docs/results.md](docs/results.md) after the first real run. Nothing in this README is a benchmark.

## What it does

1. Generates a synthetic NPCI settlement file, bank ledger, and merchant records, with planted breaks and an answer key.
2. Loads them into Exasol Personal.
3. Matches in SQL: exact → tolerance → many-to-one → residual.
4. Classifies leftovers and groups them by root cause.
5. Drafts a proposed fix. A policy gate allows, escalates, or blocks it. You approve or reject it in the UI.
6. Records every step in an audit table, with undo.

The explanation agent works with **no LLM API key** (`LLM_PROVIDER=none`). Templates write the sentences from SQL labels.

## Quick start

Full steps: [docs/run-guide.md](docs/run-guide.md).

```bash
# 1. Exasol Personal local (Apple Silicon Mac, 8 GB+ RAM)
curl https://downloads.exasol.com/exasol-personal/installer.sh | sh
export PATH="$HOME/.local/bin:$PATH"
exasol install local
exasol connect   # confirm SELECT 1;

# 2. This project
cp .env.example .env
make setup
make data
make load
make run
make test
make demo
```

`make demo` starts the Streamlit investigator screen.

## Repository layout

See the tree in this folder. Core matching logic lives in `sql/` and runs **inside Exasol**. Python loads data, runs the stages, and serves the UI.

## Licence

[MIT](LICENSE). Original work for ExaThon India 2026.

## Submission notes

- Problem statement: this README and [docs/problem-statement.md](docs/problem-statement.md)
- Run / deploy: [docs/run-guide.md](docs/run-guide.md) (local Mac; AWS optional)
- Data, APIs, tools: [docs/data-sources.md](docs/data-sources.md)
- Pitch deck: `docs/pitch/` (added before submission)
- Demo video (≤ 3 min): link will go here
