-- Collapse breaks into a few causes (gateway, break_type).

OPEN SCHEMA CLOSEDESK;

INSERT INTO root_causes (run_id, root_cause_id, title, break_count, rupees_at_risk)
SELECT
    :run_id,
    HASHTYPE_MD5(IFNULL(n.gateway_id, 'none') || '|' || b.break_type),
    'Gateway ' || IFNULL(n.gateway_id, 'unknown') || ' · ' || b.break_type,
    COUNT(*),
    SUM(b.rupees_at_risk)
FROM breaks b
LEFT JOIN npci_settlement n ON n.npci_ref = b.npci_ref
WHERE b.run_id = :run_id
GROUP BY n.gateway_id, b.break_type;

MERGE INTO breaks b
USING (
    SELECT
        br.break_id,
        HASHTYPE_MD5(
            IFNULL(ns.gateway_id, 'none') || '|' || br.break_type
        ) AS rc_id
    FROM breaks br
    LEFT JOIN npci_settlement ns ON ns.npci_ref = br.npci_ref
    WHERE br.run_id = :run_id
) src
ON b.break_id = src.break_id AND b.run_id = :run_id
WHEN MATCHED THEN UPDATE SET b.root_cause_id = src.rc_id;
