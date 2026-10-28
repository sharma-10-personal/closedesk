"""Compare engine output to planted answer key. Measure precision, recall, F1."""

from __future__ import annotations

from pathlib import Path

import pyexasol
from dotenv import dotenv_values


def _connect(env: dict[str, str | None]) -> pyexasol.ExaConnection:
    return pyexasol.connect(
        dsn=env.get("EXA_DSN", "localhost:8563"),
        user=env.get("EXA_USER", "sys"),
        password=env.get("EXA_PASSWORD", ""),
        schema=env.get("EXA_SCHEMA", "CLOSEDESK"),
        compression=True,
        websocket_sslopt={"cert_reqs": 0},
    )


# How each answer_key break type should be evaluated.
# "matched" = correct if the npci_ref IS in matches (engine reconciled it).
# "broken"  = correct if the npci_ref IS in breaks (engine flagged it).
CORRECT_IF: dict[str, str] = {
    "timing_skew": "matched",        # timestamp shift; engine should still match it
    "duplicate_ledger": "broken",     # extra ledger row should be flagged
    "amount_mismatch": "broken",      # merchant amount differs; should be a break
    "missing_settlement": "broken",   # NPCI row deleted; orphan should be flagged
    "failed_but_debited": "broken",   # NPCI FAILED but ledger DEBIT; should be flagged
    "reversal_not_posted": "broken",  # NPCI REVERSED but ledger POSTED; should be flagged
    "many_to_one_batch": "matched",   # batch should be matched via many-to-one stage
}


def score(run_id: str, env_path: Path | None = None) -> dict:
    """Return accuracy metrics for a given run_id."""
    env = dotenv_values(env_path or Path(".env"))
    conn = _connect(env)
    conn.execute("OPEN SCHEMA CLOSEDESK")

    # Get all answer_key entries
    ak_rows = conn.execute(
        "SELECT break_id, npci_ref, break_type, expected_action FROM answer_key"
    ).fetchall()

    # Get break npci_refs for this run
    break_refs: set[str] = set()
    for row in conn.execute(
        f"SELECT npci_ref FROM breaks WHERE run_id = '{run_id}' AND npci_ref IS NOT NULL"
    ).fetchall():
        break_refs.add(row[0])

    # Get matched npci_refs
    matched_refs: set[str] = set()
    for row in conn.execute(
        f"SELECT npci_ref FROM matches WHERE run_id = '{run_id}'"
    ).fetchall():
        matched_refs.add(row[0])

    results_by_type: dict[str, dict] = {}
    total_tp = total_fn = 0

    for _, npci_ref, ak_type, _ in ak_rows:
        if ak_type not in results_by_type:
            results_by_type[ak_type] = {"tp": 0, "fn": 0, "total": 0}
        results_by_type[ak_type]["total"] += 1

        correct_condition = CORRECT_IF.get(ak_type, "broken")

        if correct_condition == "matched":
            is_correct = npci_ref and npci_ref in matched_refs
        else:
            is_correct = npci_ref and npci_ref in break_refs

        if is_correct:
            results_by_type[ak_type]["tp"] += 1
            total_tp += 1
        else:
            results_by_type[ak_type]["fn"] += 1
            total_fn += 1

    # False positives: breaks with npci_ref NOT in answer_key AND not in matches
    ak_refs = {row[1] for row in ak_rows if row[1]}
    total_fp = sum(1 for ref in break_refs if ref not in ak_refs)

    precision = total_tp / max(total_tp + total_fp, 1)
    recall = total_tp / max(total_tp + total_fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)

    # Pipeline stats
    total_matched = conn.execute(
        f"SELECT COUNT(*) FROM matches WHERE run_id = '{run_id}'"
    ).fetchval()
    total_breaks = conn.execute(
        f"SELECT COUNT(*) FROM breaks WHERE run_id = '{run_id}'"
    ).fetchval()
    total_npci = conn.execute("SELECT COUNT(*) FROM npci_settlement").fetchval()
    auto_match_pct = int(total_matched) / max(int(total_npci), 1) * 100

    conn.close()

    return {
        "run_id": run_id,
        "total_answer_key": len(ak_rows),
        "total_tp": total_tp,
        "total_fp": total_fp,
        "total_fn": total_fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "auto_match_pct": round(auto_match_pct, 1),
        "total_matched": int(total_matched),
        "total_breaks": int(total_breaks),
        "by_type": results_by_type,
    }


def main() -> None:
    """CLI entry point: read latest run_id from match_stage_log and score it."""
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
    result = score(run_id)
    print(f"Run: {result['run_id']}")
    print(f"Auto-match rate: {result['auto_match_pct']:.1f}%")
    print(f"Matched: {result['total_matched']:,} | Breaks: {result['total_breaks']:,}")
    print(f"Answer key entries: {result['total_answer_key']:,}")
    print(f"True positives:  {result['total_tp']:,}")
    print(f"False positives: {result['total_fp']:,}")
    print(f"False negatives: {result['total_fn']:,}")
    print(f"Precision: {result['precision']:.2%}")
    print(f"Recall:    {result['recall']:.2%}")
    print(f"F1:        {result['f1']:.2%}")
    print()
    for bt, m in sorted(result["by_type"].items()):
        r = m["tp"] / max(m["total"], 1)
        print(f"  {bt:<25} {m['tp']:>6} / {m['total']:>6}  ({r:.0%})")


if __name__ == "__main__":
    main()
