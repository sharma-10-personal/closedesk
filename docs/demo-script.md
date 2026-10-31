# Demo Video Script (≤ 3 minutes)

Before recording: run `make full` so Exasol holds the 1M-row day, then `make demo`.

## 1. Problem (20s)

"A payments analyst at a bank gets three files every day — NPCI settlement, bank ledger, merchant records — and they disagree on thousands of transactions. She traces each one by hand. CloseDesk does the matching inside Exasol and hands her a short, ranked list."

## 2. Pipeline (40s)

Pipeline screen. Show the stage table from the 1M-row run.

"One million synthetic UPI transactions per source. Nine SQL stages run inside Exasol: exact match, tolerance, many-to-one batches, then break detection, root causes and priority. About seven seconds end to end. 99.1% matched automatically."

Optional: switch to **Upload three files**, drop the sample CSVs, click LOAD & RECONCILE. "The same pipeline runs on files you bring."

## 3. Analytics (25s)

"31,417 breaks — but only 31 root causes. Fix one gateway's problem and thousands of exceptions go away." Show the funnel and root-cause table.

## 4. Investigate one case (30s)

Investigate screen, click a high ₹ quick pick (a failed-but-debited case).

"NPCI says this payment failed, but the bank debited the customer. The agent proposed reversing the debit, and the policy gate allowed it because it's under ₹50,000."

## 5. Inject a break live (30s)

Inject screen: pick "Failed but debited", inject.

"I just wrote a new bad row into Exasol. CloseDesk detects it, classifies it, and the agent proposes a fix — in seconds."

## 6. Approve and audit (25s)

Exceptions screen: approve the proposal. Analytics → Audit Trail.

"Nothing is decided without a human. Every proposal, approval and rejection is in the audit log."

## 7. Accuracy (10s)

"Against the planted answer key: 100% precision, 99.79% recall. Details in docs/results.md."
