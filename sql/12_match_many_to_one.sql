-- Stage 3: several merchant records sum to one NPCI settlement (batch).
-- Bank ledger may not have a row for the batch npci_ref, so LEFT JOIN.
-- Engine substitutes :run_id.

OPEN SCHEMA CLOSEDESK;

INSERT INTO matches (run_id, npci_ref, ledger_id, merchant_txn_id, stage, amount_inr)
SELECT
    :run_id,
    q.npci_ref,
    q.ledger_id,
    q.merchant_txn_id,
    'many_to_one',
    q.amount_inr
FROM (
    SELECT
        n.npci_ref,
        MIN(l.ledger_id) AS ledger_id,
        MIN(m.merchant_txn_id) AS merchant_txn_id,
        n.amount_inr
    FROM npci_settlement n
    LEFT JOIN bank_ledger l
      ON l.npci_ref = n.npci_ref
    JOIN merchant_records m
      ON m.npci_ref = n.npci_ref
    JOIN (
        SELECT npci_ref, SUM(amount_inr) AS total_inr
        FROM merchant_records
        GROUP BY npci_ref
        HAVING COUNT(*) > 1
    ) ms ON ms.npci_ref = n.npci_ref AND ABS(ms.total_inr - n.amount_inr) < 1.00
    GROUP BY n.npci_ref, n.amount_inr
) q
LEFT JOIN matches x
  ON x.run_id = :run_id AND x.npci_ref = q.npci_ref
WHERE x.npci_ref IS NULL;
