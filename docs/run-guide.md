# Run Guide

Tested: Apple Silicon Mac, 16 GB RAM, Exasol Personal local VM, Python 3.13.

## 1. Exasol Personal

Needs ~8 GB RAM for the VM.

```bash
curl https://downloads.exasol.com/exasol-personal/installer.sh | sh
export PATH="$HOME/.local/bin:$PATH"
exasol install local --auto-approve --cpu-count 2 --memory-mb 8192 --data-size-gb 40
exasol status        # expect: database_ready
exasol connect -k -c "SELECT 1;"
```

Default SQL endpoint: `127.0.0.1:8563`, user `sys`. Password is in:

`~/.exasol/personal/deployments/default/secrets.json` (key `dbPassword`).

Do not commit that file. Copy it into `.env` as `EXA_PASSWORD`.

## 2. This repository

Python 3.11+ (3.13 is fine). Uses [uv](https://docs.astral.sh/uv/) for package management.

```bash
git clone https://github.com/sharma-10/closedesk.git
cd closedesk
cp .env.example .env   # set EXA_PASSWORD from secrets.json
make setup             # installs uv + Python deps
```

## 3. Full pipeline

```bash
make full
```

This runs: `data` → `schema` → `load` → `run` → `propose` → `eval`

Or run each step individually:

```bash
make data       # Generate 1M synthetic transactions (~8 min)
make schema     # Create/recreate Exasol schema
make load       # Bulk load CSVs into Exasol (~14s)
make run        # Run 9 SQL matching stages (~7s)
make propose    # Generate governed proposals (~2s)
make eval       # Score against answer key
```

## 4. Dashboard

```bash
make demo       # Opens Streamlit at localhost:8501
```

The dashboard shows:
- KPI header (match rate, ₹ at risk)
- Pipeline stage timings
- Break type distribution with chart
- Exception queue sorted by ₹ at risk
- Root cause groups
- Agent proposals with approve/reject buttons
- Full audit trail

## 5. Tests & lint

```bash
make test       # pytest (10 tests)
make lint       # ruff check
```

## 6. Reset

```bash
make reset      # Deletes data/ and recreates schema
```

## 7. What local Exasol cannot do (yet)

Python UDFs need `exasol slc install PYTHON3`. CloseDesk does not need that — all matching is plain SQL.

## 8. LLM

Leave `LLM_PROVIDER=none`. The agent generates explanations from templates + SQL labels. No API key needed.
