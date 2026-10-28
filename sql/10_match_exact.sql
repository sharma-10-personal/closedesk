-- Stage 1: exact match on npci_ref + amount + calendar day.
-- Run after 00_schema.sql. :run_id is replaced by the engine.

OPEN SCHEMA CLOSEDESK;

INSERT INTO matches (run_id, npci_ref, ledger_id, merchant_txn_id, stage, amount_inr)
SELECT
    :run_id,
    n.npci_ref,
    MIN(l.ledger_id),
    MIN(m.merchant_txn_id),
    'exact',
    n.amount_inr
FROM npci_settlement n
JOIN bank_ledger l
  ON l.npci_ref = n.npci_ref
 AND l.amount_inr = n.amount_inr
 AND TO_DATE(l.txn_ts) = TO_DATE(n.txn_ts)
JOIN merchant_records m
  ON m.npci_ref = n.npci_ref
 AND m.amount_inr = n.amount_inr
 AND TO_DATE(m.txn_ts) = TO_DATE(n.txn_ts)
GROUP BY n.npci_ref, n.amount_inr;
