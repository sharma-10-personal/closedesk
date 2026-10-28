-- Detect duplicate bank_ledger entries: multiple rows with the same npci_ref.
-- One row is the real one (already matched), extras are flagged.

OPEN SCHEMA CLOSEDESK;

INSERT INTO breaks (run_id, npci_ref, ledger_id, merchant_txn_id, break_type, amount_inr, rupees_at_risk, deadline_ts)
SELECT
    :run_id,
    dup.npci_ref,
    dup.ledger_id,
    NULL,
    'duplicate_ledger',
    dup.amount_inr,
    dup.amount_inr,
    NULL
FROM bank_ledger dup
JOIN (
    SELECT npci_ref, MIN(ledger_id) AS keep_id
    FROM bank_ledger
    WHERE npci_ref IS NOT NULL
    GROUP BY npci_ref
    HAVING COUNT(*) > 1
) g ON g.npci_ref = dup.npci_ref AND dup.ledger_id <> g.keep_id;
