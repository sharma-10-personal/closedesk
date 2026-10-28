-- Stage 3: several merchant records sum to one NPCI settlement (batch).
-- Engine substitutes :run_id.

OPEN SCHEMA CLOSEDESK;

INSERT INTO matches (run_id, npci_ref, ledger_id, merchant_txn_id, stage, amount_inr)
SELECT
    :run_id,
    n.npci_ref,
    l.ledger_id,
    m.merchant_txn_id,
    'many_to_one',
    n.amount_inr
FROM npci_settlement n
JOIN bank_ledger l
  ON l.npci_ref = n.npci_ref
 AND l.amount_inr = n.amount_inr
JOIN merchant_records m
  ON m.npci_ref = n.npci_ref
WHERE NOT EXISTS (
    SELECT 1 FROM matches x
    WHERE x.run_id = :run_id AND x.npci_ref = n.npci_ref
)
AND (
    SELECT SUM(m2.amount_inr)
    FROM merchant_records m2
    WHERE m2.npci_ref = n.npci_ref
) = n.amount_inr;
