# CloseDesk

**ExaThon India 2026 · Track: Money, Risk & Regulation**

A payments-operations analyst at a mid-size bank can't close the day's UPI reconciliation, because the settlement file, the core-banking ledger and the merchant records disagree on thousands of transactions, and she traces each one by hand across spreadsheets. If this worked, she'd start the day with a short list of true exceptions, each with a cause, the rupees at risk and a proposed fix she can approve in one click.

CloseDesk matches those three lists in **Exasol Personal**, groups leftovers by root cause, ranks them by rupees at risk, and lets an agent *propose* a fix. A human must approve every change. Nothing posts to the books without that click.

> All payment rows in this project are **synthetic**. There is no real UPI, customer, or employer data. See [docs/data-sources.md](docs/data-sources.md).

## Results (measured on 1M transactions)

| Metric | Value |
|--------|-------|
| Auto-match rate | **99.1%** |
| Precision | **100.00%** |
| Recall | **99.79%** |
| F1 score | **99.90%** |
| Wall time (9 SQL stages, 1M rows) | **6.65 seconds** |
| Break types detected | 7 / 7 (99–100% each) |
| Root-cause groups | 31 |
| Proposals generated | 31,417 |

Full details: [docs/results.md](docs/results.md)

## What it does

1. **Generate** — Creates 1M synthetic NPCI settlement, bank ledger, and merchant records with 7 planted break types and an answer key.
2. **Load** — Bulk loads all CSVs into Exasol Personal via `pyexasol.import_from_iterable()`.
3. **Match** — 3-stage SQL matching: exact → tolerance → many-to-one batch.
4. **Classify** — Identifies residual breaks: missing settlement, duplicate ledger, amount mismatch, failed-but-debited, reversal not posted, orphans.
5. **Root causes** — Groups breaks by gateway × break type, ranks by ₹ at risk.
6. **Agent** — Proposes a fix for each break. Policy gate allows, escalates, or blocks based on ₹ thresholds. Templates produce explanations (no LLM API key needed).
7. **Approve** — Human reviews each proposal in the Streamlit dashboard. Approve or reject with one click.
8. **Audit** — Every action is recorded in the audit log with before/after state.

## Quick start

Full steps: [docs/run-guide.md](docs/run-guide.md).

```bash
# 1. Exasol Personal local (Apple Silicon Mac, 8 GB+ RAM)
curl https://downloads.exasol.com/exasol-personal/installer.sh | sh
export PATH="$HOME/.local/bin:$PATH"
exasol install local
exasol connect   # confirm SELECT 1;

# 2. This project
git clone https://github.com/sharma-10/closedesk.git
cd closedesk
cp .env.example .env          # set EXA_PASSWORD from secrets.json
make setup                    # installs uv + Python deps

# 3. Full pipeline (generate → schema → load → match → propose → eval)
make full

# 4. Dashboard
make demo
```

## Repository layout

```
closedesk/
├── closedesk/
│   ├── generator/   # Synthetic data with 7 planted break types
│   ├── loader/      # Bulk CSV → Exasol via pyexasol
│   ├── engine/      # Runs SQL stages, measures timing
│   ├── agent/       # Governed proposals + policy gate
│   ├── eval/        # Accuracy scoring vs answer key
│   └── app/         # Streamlit investigator dashboard
├── sql/             # All matching logic runs INSIDE Exasol
│   ├── 00_schema.sql
│   ├── 10_match_exact.sql
│   ├── 11_match_tolerance.sql
│   ├── 12_match_many_to_one.sql
│   ├── 20_classify_breaks.sql
│   ├── 21_detect_orphans.sql
│   ├── 22_detect_duplicates.sql
│   ├── 23_detect_status_mismatch.sql
│   ├── 30_root_causes.sql
│   ├── 40_priority_and_deadlines.sql
│   └── 50_governance.sql
├── config/          # policy.yaml + scenario.yaml
├── tests/           # pytest suite (10 tests)
├── docs/            # Problem statement, architecture, results
└── data/            # Generated CSVs (gitignored)
```

Core matching logic lives in `sql/` and runs **inside Exasol**. Python loads data, orchestrates stages, and serves the UI.

## Exasol usage highlights

- **All matching happens in SQL** inside Exasol — no Python-side loops for reconciliation
- **3-stage matching** leverages Exasol's columnar engine: exact, tolerance (ABS + SECONDS_BETWEEN), many-to-one (GROUP BY + SUM)
- **1M rows matched in 3.9s** for exact stage, full pipeline in 6.65s
- **HASHTYPE_MD5** for deterministic root-cause grouping
- **MERGE INTO** for efficient batch updates
- **pyexasol.import_from_iterable()** for bulk loading (3.5s per million rows)

## Licence

[MIT](LICENSE). Original work for ExaThon India 2026.

## Submission notes

- Problem statement: this README and [docs/problem-statement.md](docs/problem-statement.md)
- Architecture: [docs/architecture.md](docs/architecture.md)
- Run / deploy: [docs/run-guide.md](docs/run-guide.md)
- Data, APIs, tools: [docs/data-sources.md](docs/data-sources.md)
- Measured results: [docs/results.md](docs/results.md)
- Pitch deck: `docs/pitch/` (added before submission)
- Demo video (≤ 3 min): link will go here
