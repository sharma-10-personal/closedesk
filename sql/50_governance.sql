-- Proposal insert helper used by the engine. Humans decide in the UI.
-- Engine binds :proposal_id, :run_id, :break_id, :action, :explanation,
-- :amount_inr, :gate_decision, :actor.

OPEN SCHEMA CLOSEDESK;

INSERT INTO proposals (
    proposal_id, run_id, break_id, action_name, explanation,
    amount_inr, gate_decision, status, created_at
)
VALUES (
    :proposal_id, :run_id, :break_id, :action, :explanation,
    :amount_inr, :gate_decision, 'PENDING', NOW()
);

INSERT INTO audit_log (at_ts, actor, action_name, entity_type, entity_id, before_json, after_json)
VALUES (
    NOW(), :actor, 'PROPOSE', 'proposal', :proposal_id, NULL, :explanation
);
