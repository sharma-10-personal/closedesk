"""Test agent policy gate and action mapping."""

from closedesk.agent.policy import Policy, gate
from closedesk.agent.propose import ACTION_MAP


def test_all_break_types_have_actions():
    expected = {
        "missing_ledger",
        "missing_merchant",
        "missing_bank_and_merchant",
        "amount_mismatch",
        "failed_but_debited",
        "duplicate_ledger",
        "reversal_not_posted",
        "missing_settlement",
        "unclassified",
    }
    assert expected <= set(ACTION_MAP.keys())


def test_action_map_values_are_allowed():
    policy = Policy(
        auto_propose_max_inr=50000,
        escalate_above_inr=500000,
        allowed_actions=(
            "post_missing_credit",
            "reverse_failed_debit",
            "flag_duplicate",
            "notify_merchant_mismatch",
            "no_action_explain",
        ),
    )
    for break_type, (action, _) in ACTION_MAP.items():
        result = gate(action, 100.0, policy)
        assert result == "allow", f"{break_type} → {action} was {result}"


def test_gate_escalates_large_amount():
    policy = Policy(
        auto_propose_max_inr=50000,
        escalate_above_inr=500000,
        allowed_actions=("reverse_failed_debit",),
    )
    assert gate("reverse_failed_debit", 100000, policy) == "escalate"


def test_gate_blocks_above_escalation():
    policy = Policy(
        auto_propose_max_inr=50000,
        escalate_above_inr=500000,
        allowed_actions=("reverse_failed_debit",),
    )
    assert gate("reverse_failed_debit", 600000, policy) == "block"
