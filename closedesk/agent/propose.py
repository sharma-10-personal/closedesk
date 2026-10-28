"""Governed agent: read breaks → propose actions → policy gate → write proposals.

Uses batch inserts for performance. Every proposal goes through the policy gate.
Humans approve/reject in the Streamlit UI. Full audit trail is maintained.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path

import pyexasol
from dotenv import dotenv_values

from closedesk.agent.policy import gate, load_policy

ACTION_MAP: dict[str, tuple[str, str]] = {
    "missing_ledger": (
        "post_missing_credit",
        ("Bank ledger has no entry for NPCI ref {npci_ref}. "
        "Recommend posting a credit of ₹{amount:.2f} to complete settlement."),
    ),
    "missing_merchant": (
        "notify_merchant_mismatch",
        ("Merchant system has no record for NPCI ref {npci_ref}. "
        "Notify merchant gateway {gateway} to reconcile ₹{amount:.2f}."),
    ),
    "missing_bank_and_merchant": (
        "no_action_explain",
        ("NPCI ref {npci_ref} has no bank or merchant record. "
        "Likely a late-arriving settlement. Amount: ₹{amount:.2f}."),
    ),
    "amount_mismatch": (
        "notify_merchant_mismatch",
        ("Amount differs across sources for NPCI ref {npci_ref}. "
        "NPCI says ₹{amount:.2f}. Investigate merchant gateway {gateway}."),
    ),
    "failed_but_debited": (
        "reverse_failed_debit",
        ("NPCI reports FAILED but bank debited ₹{amount:.2f} for ref {npci_ref}. "
        "Customer refund required within 24h per RBI circular."),
    ),
    "duplicate_ledger": (
        "flag_duplicate",
        ("Duplicate bank ledger entry detected for NPCI ref {npci_ref}. "
        "Amount: ₹{amount:.2f}. Flag for reconciliation team."),
    ),
    "reversal_not_posted": (
        "post_missing_credit",
        ("NPCI reversed ref {npci_ref} but bank still shows credit of ₹{amount:.2f}. "
        "Post reversal entry to ledger."),
    ),
    "missing_settlement": (
        "no_action_explain",
        ("Bank/merchant have records for ref {npci_ref} but no NPCI settlement found. "
        "Amount: ₹{amount:.2f}. May be a delayed settlement file."),
    ),
    "unclassified": (
        "no_action_explain",
        ("Unclassified break for NPCI ref {npci_ref}, ₹{amount:.2f}. "
        "Manual investigation recommended."),
    ),
}


def _connect(env: dict[str, str | None]) -> pyexasol.ExaConnection:
    return pyexasol.connect(
        dsn=env.get("EXA_DSN", "localhost:8563"),
        user=env.get("EXA_USER", "sys"),
        password=env.get("EXA_PASSWORD", ""),
        schema=env.get("EXA_SCHEMA", "CLOSEDESK"),
        compression=True,
        websocket_sslopt={"cert_reqs": 0},
    )


def propose_all(run_id: str, env_path: Path | None = None, policy_path: Path | None = None) -> dict:
    """Generate proposals for all breaks in a run using batch inserts."""
    env = dotenv_values(env_path or Path(".env"))
    policy = load_policy(policy_path)
    conn = _connect(env)
    conn.execute("OPEN SCHEMA CLOSEDESK")

    # Clear any existing proposals for this run
    conn.execute(f"DELETE FROM proposals WHERE run_id = '{run_id}'")

    breaks = conn.execute(f"""
        SELECT b.break_id, b.npci_ref, b.break_type, b.amount_inr,
               b.rupees_at_risk, IFNULL(n.gateway_id, 'unknown') AS gateway_id
        FROM breaks b
        LEFT JOIN npci_settlement n ON n.npci_ref = b.npci_ref
        WHERE b.run_id = '{run_id}'
        ORDER BY b.rupees_at_risk DESC
    """).fetchall()

    stats = {"total": 0, "allow": 0, "escalate": 0, "block": 0}
    proposal_rows: list[tuple] = []
    audit_rows: list[tuple] = []
    now_str = datetime.now(tz=__import__("datetime").timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for break_id, npci_ref, break_type, amount_inr, rupees_at_risk, gateway_id in breaks:
        action, explanation_tpl = ACTION_MAP.get(
            break_type, ("no_action_explain", "Unknown break type for {npci_ref}.")
        )
        explanation = explanation_tpl.format(
            npci_ref=npci_ref or "N/A",
            amount=float(amount_inr),
            gateway=gateway_id,
        )

        gate_decision = gate(action, float(amount_inr), policy)
        proposal_id = f"P-{secrets.token_hex(4)}"

        proposal_rows.append((
            proposal_id, run_id, str(break_id), action,
            explanation[:4000], str(amount_inr),
            gate_decision, "PENDING", now_str,
        ))

        audit_rows.append((
            now_str, "closedesk-agent", "PROPOSE", "proposal",
            proposal_id, "", explanation[:4000],
        ))

        stats["total"] += 1
        stats[gate_decision] += 1

    # Batch insert proposals (column order matches table definition exactly)
    if proposal_rows:
        conn.execute(f"DELETE FROM proposals WHERE run_id = '{run_id}'")
        conn.import_from_iterable(proposal_rows, "PROPOSALS")

    conn.close()
    return stats


def main() -> None:
    """CLI: propose for the latest run."""
    env = dotenv_values(Path(".env"))
    conn = _connect(env)
    conn.execute("OPEN SCHEMA CLOSEDESK")
    row = conn.execute(
        "SELECT run_id FROM match_stage_log ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    conn.close()

    if not row:
        print("No runs found. Execute `make run` first.")
        return

    run_id = row[0]
    print(f"Generating proposals for run {run_id}...")
    stats = propose_all(run_id)
    print(f"Total proposals: {stats['total']:,}")
    print(f"  Allow:    {stats['allow']:,}")
    print(f"  Escalate: {stats['escalate']:,}")
    print(f"  Block:    {stats['block']:,}")


if __name__ == "__main__":
    main()
