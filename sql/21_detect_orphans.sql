-- Detect orphan bank_ledger rows: npci_ref not found in npci_settlement.
-- These correspond to "missing_settlement" breaks.

OPEN SCHEMA CLOSEDESK;

INSERT INTO breaks (run_id, npci_ref, ledger_id, merchant_txn_id, break_type, amount_inr, rupees_at_risk, deadline_ts)
SELECT
    :run_id,
    l.npci_ref,
    l.ledger_id,
    m.merchant_txn_id,
    'missing_settlement',
    l.amount_inr,
    l.amount_inr,
    NULL
FROM bank_ledger l
LEFT JOIN npci_settlement n ON n.npci_ref = l.npci_ref
LEFT JOIN merchant_records m ON m.npci_ref = l.npci_ref
WHERE n.npci_ref IS NULL
  AND l.npci_ref IS NOT NULL;
