-- Detect status contradictions.
-- reversal_not_posted: NPCI says REVERSED but ledger still shows CREDIT/POSTED.

OPEN SCHEMA CLOSEDESK;

INSERT INTO breaks (run_id, npci_ref, ledger_id, merchant_txn_id, break_type, amount_inr, rupees_at_risk, deadline_ts)
SELECT
    :run_id,
    n.npci_ref,
    l.ledger_id,
    NULL,
    'reversal_not_posted',
    n.amount_inr,
    n.amount_inr,
    NULL
FROM npci_settlement n
JOIN bank_ledger l
  ON l.npci_ref = n.npci_ref
WHERE n.status = 'REVERSED'
  AND l.direction = 'CREDIT'
  AND l.status = 'POSTED';
