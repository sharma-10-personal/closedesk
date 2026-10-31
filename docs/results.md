# Measured Results

All figures from a single run on a 2024 MacBook (Exasol Personal 2026.2.0-nano.3, pyexasol 0.28, Python 3.13).

## Pipeline Summary

| Metric | Value |
|--------|-------|
| Base transactions | 1,000,000 |
| Rows loaded (NPCI / ledger / merchant) | 989,666 / 1,004,000 / 994,000 |
| Auto-match rate | 99.1% |
| Total matched | 980,583 |
| Total breaks | 31,417 |
| Total wall time | 6.65 s |

A rerun on 31 Oct 2026 (run `R-2026-10-27-dee303`) reproduced every row count and accuracy figure exactly. Wall time was 7.71 s; timings vary by a second or so between runs on this VM.

## Stage Timings

| Stage | Rows | ₹ Value | Time |
|-------|------|---------|------|
| Exact match | 977,846 | ₹48.9B | 3.92s |
| Tolerance | 70 | ₹3.5M | 0.57s |
| Many-to-one batch | 2,667 | ₹400M | 0.68s |
| Classify breaks | 15,083 | ₹755M | 0.33s |
| Orphan detection | 20,083 | ₹1.0B | 0.16s |
| Duplicate detection | 29,417 | ₹1.47B | 0.77s |
| Status mismatch | 31,417 | ₹1.57B | 0.09s |
| Root causes | 31 groups | ₹1.57B | 0.10s |
| Priority ranking | 31,417 | ₹1.57B | 0.03s |

## Accuracy vs Planted Answer Key

| Metric | Value |
|--------|-------|
| Answer key entries | 40,001 |
| True positives | 39,918 |
| False positives | 0 |
| False negatives | 83 |
| **Precision** | **100.00%** |
| **Recall** | **99.79%** |
| **F1** | **99.90%** |

## Detection by Break Type

| Break Type | Detected / Planted | Rate |
|------------|-------------------|------|
| amount_mismatch | 3,000 / 3,000 | 100% |
| duplicate_ledger | 4,000 / 4,000 | 100% |
| failed_but_debited | 6,000 / 6,000 | 100% |
| many_to_one_batch | 8,001 / 8,001 | 100% |
| missing_settlement | 5,000 / 5,000 | 100% |
| reversal_not_posted | 2,000 / 2,000 | 100% |
| timing_skew | 11,917 / 12,000 | 99% |

83 timing_skew false negatives are transactions shifted past midnight into a different calendar day, causing `TO_DATE()` mismatch and an exact-match miss followed by tolerance-match miss (amount matches but date filter excludes them).

## Root Causes

31 root-cause groups cover all 31,417 breaks. Each group combines gateway + break type. Top groups by ₹ at risk are available in the Streamlit dashboard.
