# Architecture

## Data Flow

```
┌─────────────────────────┐
│  Synthetic Generator    │  1M rows × 3 sources + 7 break types
│  closedesk/generator/   │  Deterministic (seed 20261028)
└──────────┬──────────────┘
           │  data/*.csv
           ▼
┌─────────────────────────┐
│  Bulk Loader            │  pyexasol.import_from_iterable()
│  closedesk/loader/      │  ~3s per million rows
└──────────┬──────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│  Exasol Personal (CLOSEDESK schema)                      │
│                                                          │
│  sql/10_match_exact.sql       → matches (exact)          │
│  sql/11_match_tolerance.sql   → matches (tolerance)      │
│  sql/12_match_many_to_one.sql → matches (many_to_one)    │
│  sql/20_classify_breaks.sql   → breaks (classify)        │
│  sql/21_detect_orphans.sql    → breaks (orphans)         │
│  sql/22_detect_duplicates.sql → breaks (duplicates)      │
│  sql/23_detect_status_mismatch.sql → breaks (status)     │
│  sql/30_root_causes.sql       → root_causes              │
│  sql/40_priority_and_deadlines.sql → breaks (ranked)     │
│                                                          │
│  All matching logic runs INSIDE Exasol. No Python UDFs.  │
└──────────┬───────────────────────────┬───────────────────┘
           │                           │
           ▼                           ▼
┌──────────────────────┐   ┌───────────────────────────┐
│  Governed Agent      │   │  Eval Module              │
│  closedesk/agent/    │   │  closedesk/eval/          │
│                      │   │                           │
│  • Reads breaks      │   │  • Compares to answer key │
│  • Maps to actions   │   │  • Precision / Recall / F1│
│  • Policy gate       │   │  • Per-break-type scores  │
│  • Writes proposals  │   └───────────────────────────┘
│  • Audit log         │
└──────────┬───────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│  Streamlit Dashboard (closedesk/app/ui.py)      │
│                                                 │
│  Pipeline     generate a day or upload 3 CSVs,  │
│               stages run live in Exasol         │
│  Investigate  one NPCI ref across all 3 sources │
│  Inject       plant a break, watch it detected  │
│  Exceptions   proposal queue, approve / reject  │
│  Analytics    funnel, root causes, audit trail  │
└─────────────────────────────────────────────────┘
```

Uploaded CSVs are validated in Python (headers, column counts, amounts, duplicate IDs), saved to `data/upload/`, then loaded with the same bulk loader and matched by the same SQL stages.

## Schema (11 tables)

| Table | Purpose |
|-------|---------|
| `npci_settlement` | NPCI settlement file (PK: npci_ref) |
| `bank_ledger` | Core banking ledger (PK: ledger_id) |
| `merchant_records` | Merchant payment records (PK: merchant_txn_id) |
| `answer_key` | Planted truth for evaluation only |
| `match_stage_log` | Timing and row counts per SQL stage |
| `matches` | Successfully reconciled rows (PK: run_id, npci_ref, stage) |
| `breaks` | Unreconciled rows with classification |
| `root_causes` | Grouped by gateway × break_type |
| `proposals` | Agent-proposed fixes (PENDING/APPROVED/REJECTED) |
| `decisions` | Human approve/reject records |
| `audit_log` | Complete action trail with before/after state |

## Governance Model

1. **Agent reads** breaks via query (ideally read-only user)
2. **Agent proposes** an action for each break → writes to `proposals`
3. **Policy gate** checks ₹ amount against thresholds:
   - ≤ ₹50,000 → `allow` (one-click approve)
   - ₹50,001 – ₹5,00,000 → `escalate` (supervisor required)
   - > ₹5,00,000 → `block` (manual process only)
4. **Human approves/rejects** in Streamlit UI
5. **Decision + audit** recorded in `decisions` and `audit_log`

## What was verified on this Mac (28 Oct 2026)

- Product: Exasol Personal **2026.2.0-nano.3**
- Local VM, 2 vCPU, ~6.6 GB DB RAM, max 20 connections
- SQL: **works** — all 9 stages run in 6.65s on 1M rows
- Lua scalar scripts: **work** without extra packages
- Python3 UDFs: **do not work** until `exasol slc install PYTHON3`
- `IMPORT ... FROM LOCAL CSV FILE`: **failed** (SSL). Load path: **pyexasol bulk import**
- `pyexasol.import_from_iterable()`: **3.5s per million rows**

CloseDesk keeps all matching, classification, and grouping in **plain SQL**. No Python UDF is required.
