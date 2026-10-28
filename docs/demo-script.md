# Demo Video Script (≤ 3 minutes)

## 1. Problem (20s)

"A payments analyst at a bank gets three files every day — NPCI settlement, bank ledger, merchant records — and they disagree on thousands of transactions. She traces each one by hand. Let me show you how CloseDesk fixes this."

## 2. Load (15s)

Show terminal:
```bash
make load    # 1M rows loaded in ~14 seconds
```
"We generated 1 million synthetic UPI transactions with 7 types of planted breaks."

## 3. Match (40s)

Show terminal:
```bash
make run
```
"Watch the stages. Exact match: 977K rows in 3 seconds. Tolerance: catches 70 more. Many-to-one batch: 2,667. Total auto-match rate: 99.1%."

Point out the timing table.

## 4. Breaks & Root Causes (30s)

Open Streamlit dashboard (`make demo`).

Show the KPI header: "Out of 1M transactions, 31,417 breaks detected, grouped into just 31 root causes."

Click the Root Causes tab. "Each root cause is a gateway × break type combination. The top ones have the most rupees at risk."

## 5. One Case: Failed-but-Debited (40s)

Click Breaks tab, filter by `failed_but_debited`.

"NPCI says this transaction FAILED, but the bank debited the customer's account. RBI requires a refund within 24 hours."

Click Proposals tab. "The agent already proposed 'reverse_failed_debit' with an explanation. The policy gate approved it because it's under ₹50,000."

Click ✅ Approve. "Decision recorded. Audit trail updated."

## 6. Governance (20s)

Click Audit Log tab. "Every action — PROPOSE, APPROVE, REJECT — is recorded with actor, timestamp, and before/after state. Nothing happens without human approval."

## 7. Accuracy (15s)

"Against our planted answer key: 100% precision, 99.79% recall, F1 of 99.9%. All 7 break types detected. Full numbers in docs/results.md."
