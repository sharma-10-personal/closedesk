-- Collapse breaks into a few causes (gateway, merchant, break_type).

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

UPDATE breaks b
SET root_cause_id = (
    SELECT r.root_cause_id
    FROM root_causes r
    WHERE r.run_id = b.run_id
      AND r.root_cause_id = HASHTYPE_MD5(
            IFNULL((SELECT n.gateway_id FROM npci_settlement n WHERE n.npci_ref = b.npci_ref), 'none')
            || '|' || b.break_type
      )
)
WHERE b.run_id = :run_id;
