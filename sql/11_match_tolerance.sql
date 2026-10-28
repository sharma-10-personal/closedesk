-- Stage 2: same npci_ref, amount within tolerance, timestamps within N seconds.
-- Bindings :run_id, :amount_tol, :time_tol_seconds replaced by the engine.

OPEN SCHEMA CLOSEDESK;

INSERT INTO matches (run_id, npci_ref, ledger_id, merchant_txn_id, stage, amount_inr)
SELECT
    :run_id,
    n.npci_ref,
    MIN(l.ledger_id),
    MIN(m.merchant_txn_id),
    'tolerance',
    n.amount_inr
FROM npci_settlement n
JOIN bank_ledger l
  ON l.npci_ref = n.npci_ref
 AND ABS(l.amount_inr - n.amount_inr) <= :amount_tol
 AND ABS(SECONDS_BETWEEN(l.txn_ts, n.txn_ts)) <= :time_tol_seconds
JOIN merchant_records m
  ON m.npci_ref = n.npci_ref
 AND ABS(m.amount_inr - n.amount_inr) <= :amount_tol
 AND ABS(SECONDS_BETWEEN(m.txn_ts, n.txn_ts)) <= :time_tol_seconds
WHERE NOT EXISTS (
    SELECT 1 FROM matches x
    WHERE x.run_id = :run_id AND x.npci_ref = n.npci_ref
)
GROUP BY n.npci_ref, n.amount_inr;
