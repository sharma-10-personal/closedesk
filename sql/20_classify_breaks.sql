-- Residual rows become breaks. Rules only; no LLM.

OPEN SCHEMA CLOSEDESK;

-- NPCI row with no match.
INSERT INTO breaks (run_id, npci_ref, ledger_id, merchant_txn_id, break_type, amount_inr, rupees_at_risk, deadline_ts)
SELECT
    :run_id,
    q.npci_ref,
    q.ledger_id,
    q.merchant_txn_id,
    CASE
        WHEN q.ledger_id IS NULL AND q.merchant_txn_id IS NULL THEN 'missing_bank_and_merchant'
        WHEN q.ledger_id IS NULL THEN 'missing_ledger'
        WHEN q.merchant_txn_id IS NULL THEN 'missing_merchant'
        WHEN q.ledger_amount <> q.amount_inr OR q.merchant_amount <> q.amount_inr THEN 'amount_mismatch'
        ELSE 'unclassified'
    END,
    q.amount_inr,
    q.amount_inr,
    NULL
FROM (
    SELECT
        n.npci_ref,
        MIN(l.ledger_id) AS ledger_id,
        MIN(l.amount_inr) AS ledger_amount,
        MIN(m.merchant_txn_id) AS merchant_txn_id,
        MIN(m.amount_inr) AS merchant_amount,
        n.amount_inr
    FROM npci_settlement n
    LEFT JOIN bank_ledger l ON l.npci_ref = n.npci_ref
    LEFT JOIN merchant_records m ON m.npci_ref = n.npci_ref
    LEFT JOIN matches x ON x.run_id = :run_id AND x.npci_ref = n.npci_ref
    WHERE x.npci_ref IS NULL
    GROUP BY n.npci_ref, n.amount_inr
) q;

-- Failed-but-debited: ledger debit with no NPCI success.
INSERT INTO breaks (run_id, npci_ref, ledger_id, merchant_txn_id, break_type, amount_inr, rupees_at_risk, deadline_ts)
SELECT
    :run_id,
    l.npci_ref,
    l.ledger_id,
    NULL,
    'failed_but_debited',
    l.amount_inr,
    l.amount_inr,
    ADD_HOURS(l.posting_ts, 24)
FROM bank_ledger l
WHERE l.direction = 'DEBIT'
  AND l.status = 'POSTED'
  AND (l.npci_ref IS NULL OR NOT EXISTS (
        SELECT 1 FROM npci_settlement n WHERE n.npci_ref = l.npci_ref AND n.status = 'SUCCESS'
  ));
