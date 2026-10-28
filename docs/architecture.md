# Architecture

```
synthetic generator
        |
        v
  NPCI file | bank ledger | merchant records | answer key
        |
        v
   pyexasol bulk load
        |
        v
 Exasol Personal (CLOSEDESK schema)
   sql/10 exact
   sql/11 tolerance
   sql/12 many-to-one
   sql/20 classify
   sql/30 root causes
   sql/40 priority
   sql/50 proposals + audit
        |
        +--> read-only user --> explanation agent (templates, optional LLM)
        |
        v
 Streamlit: unmatched ₹, causes, queue, approve/reject
```

## What was verified on this Mac (28 Oct 2026)

- Product: Exasol Personal **2026.2.0-nano.3**
- Local VM, 2 vCPU, ~6.6 GB DB RAM, max 20 connections
- `SELECT 1` and ordinary INSERT/SELECT: **work**
- Lua scalar scripts: **work** without extra packages
- Python3 UDFs: **do not work** until `exasol slc install PYTHON3`
- `IMPORT ... FROM LOCAL CSV FILE` against the VM shared folder: **failed** in this probe (file/SSL). Load path is **pyexasol**, not server-side CSV import.

CloseDesk therefore keeps matching, classification, and grouping in **plain SQL**. No Python UDF is required.

## Governance

The agent uses a **read-only** database user. Writes go only to `proposals` and `audit_log`. `decisions` are written when a human clicks in the UI. Policy lives in `config/policy.yaml`.
