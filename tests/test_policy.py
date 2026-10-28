from pathlib import Path

from closedesk.agent.policy import gate, load_policy


def test_load_policy_from_repo():
    policy = load_policy(Path("config/policy.yaml"))
    assert policy.auto_propose_max_inr == 50000
    assert "reverse_failed_debit" in policy.allowed_actions


def test_gate_allow_escalate_block():
    policy = load_policy(Path("config/policy.yaml"))
    assert gate("reverse_failed_debit", 1000, policy) == "allow"
    assert gate("reverse_failed_debit", 80_000, policy) == "escalate"
    assert gate("reverse_failed_debit", 600_000, policy) == "block"
    assert gate("wire_to_cayman", 10, policy) == "block"
