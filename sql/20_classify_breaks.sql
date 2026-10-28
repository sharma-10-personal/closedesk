-- Residual rows become breaks. Rules only; no LLM.

OPEN SCHEMA CLOSEDESK;

-- NPCI row with no exact/tolerance/many-to-one match.
INSERT INTO breaks (run_id, npci_ref, ledger_id, merchant_txn_id, break_type, amount_inr, rupees_at_risk, deadline_ts)
SELECT
    :run_id,
    n.npci_ref,
    l.ledger_id,
    m.merchant_txn_id,
    CASE
        WHEN l.ledger_id IS NULL AND m.merchant_txn_id IS NULL THEN 'missing_bank_and_merchant'
        WHEN l.ledger_id IS NULL THEN 'missing_ledger'
        WHEN m.merchant_txn_id IS NULL THEN 'missing_merchant'
        WHEN l.amount_inr <> n.amount_inr OR m.amount_inr <> n.amount_inr THEN 'amount_mismatch'
        ELSE 'unclassified'
    END,
    n.amount_inr,
    n.amount_inr,
    NULL
FROM npci_settlement n
LEFT JOIN bank_ledger l ON l.npci_ref = n.npci_ref
LEFT JOIN merchant_records m ON m.npci_ref = n.npci_ref
WHERE NOT EXISTS (
    SELECT 1 FROM matches x
    WHERE x.run_id = :run_id AND x.npci_ref = n.npci_ref
);

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
