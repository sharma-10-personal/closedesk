"""CloseDesk Streamlit dashboard — governed UPI reconciliation investigator."""

from __future__ import annotations

from pathlib import Path

import pyexasol
import streamlit as st
from dotenv import dotenv_values

st.set_page_config(page_title="CloseDesk", page_icon="🏦", layout="wide")


@st.cache_resource
def _connect():
    env = dotenv_values(Path(".env"))
    return pyexasol.connect(
        dsn=env.get("EXA_DSN", "localhost:8563"),
        user=env.get("EXA_USER", "sys"),
        password=env.get("EXA_PASSWORD", ""),
        schema=env.get("EXA_SCHEMA", "CLOSEDESK"),
        compression=True,
        websocket_sslopt={"cert_reqs": 0},
    )


def _q(sql: str):
    """Execute SQL and return list of tuples."""
    conn = _connect()
    return conn.execute(sql).fetchall()


def _qone(sql: str):
    """Execute SQL and return scalar."""
    conn = _connect()
    return conn.execute(sql).fetchval()


def _latest_run_id() -> str | None:
    try:
        return _qone("SELECT run_id FROM match_stage_log ORDER BY started_at DESC LIMIT 1")
    except (pyexasol.ExaQueryError, pyexasol.ExaConnectionError):
        return None


# ── Sidebar ──────────────────────────────────────────────────────────
st.sidebar.title("🏦 CloseDesk")
st.sidebar.caption("Governed UPI Reconciliation")

run_id = _latest_run_id()
if not run_id:
    st.error("No runs found. Run `make run` first to process data.")
    st.stop()

st.sidebar.markdown(f"**Run:** `{run_id}`")

# ── KPI Header ───────────────────────────────────────────────────────
st.title("CloseDesk — UPI Reconciliation Dashboard")

col1, col2, col3, col4, col5 = st.columns(5)

total_npci = int(_qone("SELECT COUNT(*) FROM npci_settlement"))
total_matched = int(_qone(f"SELECT COUNT(*) FROM matches WHERE run_id = '{run_id}'"))
total_breaks = int(_qone(f"SELECT COUNT(*) FROM breaks WHERE run_id = '{run_id}'"))
match_rate = total_matched / max(total_npci, 1) * 100

rupees_matched = float(_qone(
    f"SELECT COALESCE(SUM(amount_inr), 0) FROM matches WHERE run_id = '{run_id}'"
))
rupees_at_risk = float(_qone(
    f"SELECT COALESCE(SUM(rupees_at_risk), 0) FROM breaks WHERE run_id = '{run_id}'"
))

col1.metric("NPCI Transactions", f"{total_npci:,}")
col2.metric("Auto-Matched", f"{total_matched:,}", f"{match_rate:.1f}%")
col3.metric("Breaks Detected", f"{total_breaks:,}")
col4.metric("₹ Reconciled", f"₹{rupees_matched/1e7:,.0f} Cr")
col5.metric("₹ At Risk", f"₹{rupees_at_risk/1e7:,.0f} Cr", delta_color="inverse")

st.divider()

# ── Tabs ─────────────────────────────────────────────────────────────
tab_overview, tab_breaks, tab_root, tab_proposals, tab_audit = st.tabs(
    ["📊 Overview", "🔍 Breaks", "🌳 Root Causes", "📋 Proposals", "📜 Audit Log"]
)

# ── Tab 1: Overview ──────────────────────────────────────────────────
with tab_overview:
    st.subheader("Pipeline Stage Summary")

    stages = _q(f"""
        SELECT stage, rows_matched, rupees_matched, elapsed_ms
        FROM match_stage_log
        WHERE run_id = '{run_id}'
        ORDER BY started_at
    """)

    if stages:
        import pandas as pd
        df = pd.DataFrame(stages, columns=["Stage", "Rows", "₹ Value", "Time (ms)"])
        df["₹ Value"] = df["₹ Value"].apply(lambda x: f"₹{float(x):,.2f}")
        df["Time (ms)"] = df["Time (ms)"].apply(lambda x: f"{float(x):,.0f}")
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("Break Type Distribution")
    break_dist = _q(f"""
        SELECT break_type, COUNT(*) AS cnt, SUM(rupees_at_risk) AS risk
        FROM breaks WHERE run_id = '{run_id}'
        GROUP BY break_type
        ORDER BY risk DESC
    """)
    if break_dist:
        import pandas as pd
        df_b = pd.DataFrame(break_dist, columns=["Break Type", "Count", "₹ At Risk"])
        df_b["₹ At Risk"] = df_b["₹ At Risk"].apply(lambda x: f"₹{float(x):,.2f}")
        st.dataframe(df_b, use_container_width=True, hide_index=True)

        chart_data = pd.DataFrame(
            [(row[0], int(row[1])) for row in break_dist],
            columns=["Type", "Count"],
        )
        st.bar_chart(chart_data, x="Type", y="Count")

# ── Tab 2: Breaks ────────────────────────────────────────────────────
with tab_breaks:
    st.subheader("Exception Queue — Sorted by ₹ At Risk")

    break_type_filter = st.selectbox(
        "Filter by break type",
        ["All"] + [r[0] for r in _q(
            f"SELECT DISTINCT break_type FROM breaks WHERE run_id = '{run_id}' ORDER BY 1"
        )],
    )

    where = f"WHERE b.run_id = '{run_id}'"
    if break_type_filter != "All":
        where += f" AND b.break_type = '{break_type_filter}'"

    breaks_list = _q(f"""
        SELECT b.break_id, b.npci_ref, b.break_type, b.amount_inr,
               b.rupees_at_risk, IFNULL(n.gateway_id, '-') AS gw
        FROM breaks b
        LEFT JOIN npci_settlement n ON n.npci_ref = b.npci_ref
        {where}
        ORDER BY b.rupees_at_risk DESC
        LIMIT 100
    """)

    if breaks_list:
        import pandas as pd
        df_br = pd.DataFrame(
            breaks_list,
            columns=["ID", "NPCI Ref", "Type", "Amount (₹)", "₹ At Risk", "Gateway"],
        )
        df_br["Amount (₹)"] = df_br["Amount (₹)"].apply(lambda x: f"₹{float(x):,.2f}")
        df_br["₹ At Risk"] = df_br["₹ At Risk"].apply(lambda x: f"₹{float(x):,.2f}")
        st.dataframe(df_br, use_container_width=True, hide_index=True)
    else:
        st.info("No breaks found for this filter.")

# ── Tab 3: Root Causes ───────────────────────────────────────────────
with tab_root:
    st.subheader("Root Cause Groups")

    roots = _q(f"""
        SELECT root_cause_id, title, break_count, rupees_at_risk
        FROM root_causes
        WHERE run_id = '{run_id}'
        ORDER BY rupees_at_risk DESC
    """)

    if roots:
        import pandas as pd
        df_rc = pd.DataFrame(roots, columns=["ID", "Title", "Breaks", "₹ At Risk"])
        df_rc["₹ At Risk"] = df_rc["₹ At Risk"].apply(lambda x: f"₹{float(x):,.2f}")
        st.dataframe(df_rc, use_container_width=True, hide_index=True)
    else:
        st.info("No root causes computed yet.")

# ── Tab 4: Proposals ─────────────────────────────────────────────────
with tab_proposals:
    st.subheader("Agent Proposals — Human Approval Required")

    proposals = _q(f"""
        SELECT p.proposal_id, p.break_id, p.action_name, p.explanation,
               p.amount_inr, p.gate_decision, p.status
        FROM proposals p
        WHERE p.run_id = '{run_id}'
        ORDER BY p.amount_inr DESC
        LIMIT 50
    """)

    if proposals:
        for pid, bid, action, explanation, amount, gate_dec, status in proposals:
            gate_color = {"allow": "🟢", "escalate": "🟡", "block": "🔴"}.get(gate_dec, "⚪")
            status_badge = {"PENDING": "⏳", "APPROVED": "✅", "REJECTED": "❌"}.get(status, "")

            with st.expander(
                f"{gate_color} {status_badge} {action} — ₹{float(amount):,.2f} [{gate_dec}]"
            ):
                st.markdown(f"**Proposal:** `{pid}`  |  **Break:** `{bid}`")
                st.markdown(f"**Explanation:** {explanation}")
                st.markdown(f"**Gate:** {gate_dec}  |  **Status:** {status}")

                if status == "PENDING":
                    col_a, col_r = st.columns(2)
                    with col_a:
                        if st.button("✅ Approve", key=f"approve_{pid}"):
                            conn = _connect()
                            did = f"D-{__import__('secrets').token_hex(4)}"
                            conn.execute(f"""
                                INSERT INTO decisions
                                (decision_id, proposal_id, decided_by, decision_name, decided_at, note)
                                VALUES ('{did}', '{pid}', 'investigator', 'APPROVED', NOW(), 'Approved via UI')
                            """)
                            conn.execute(f"UPDATE proposals SET status = 'APPROVED' WHERE proposal_id = '{pid}'")
                            conn.execute(f"""
                                INSERT INTO audit_log (at_ts, actor, action_name, entity_type, entity_id, before_json, after_json)
                                VALUES (NOW(), 'investigator', 'APPROVE', 'proposal', '{pid}', 'PENDING', 'APPROVED')
                            """)
                            st.rerun()
                    with col_r:
                        if st.button("❌ Reject", key=f"reject_{pid}"):
                            conn = _connect()
                            did = f"D-{__import__('secrets').token_hex(4)}"
                            conn.execute(f"""
                                INSERT INTO decisions
                                (decision_id, proposal_id, decided_by, decision_name, decided_at, note)
                                VALUES ('{did}', '{pid}', 'investigator', 'REJECTED', NOW(), 'Rejected via UI')
                            """)
                            conn.execute(f"UPDATE proposals SET status = 'REJECTED' WHERE proposal_id = '{pid}'")
                            conn.execute(f"""
                                INSERT INTO audit_log (at_ts, actor, action_name, entity_type, entity_id, before_json, after_json)
                                VALUES (NOW(), 'investigator', 'REJECT', 'proposal', '{pid}', 'PENDING', 'REJECTED')
                            """)
                            st.rerun()
    else:
        st.info("No proposals yet. Run `python -m closedesk.agent` to generate proposals.")

# ── Tab 5: Audit Log ─────────────────────────────────────────────────
with tab_audit:
    st.subheader("Full Audit Trail")

    audits = _q("""
        SELECT audit_id, at_ts, actor, action_name, entity_type, entity_id,
               IFNULL(before_json, '-'), IFNULL(after_json, '-')
        FROM audit_log
        ORDER BY audit_id DESC
        LIMIT 100
    """)

    if audits:
        import pandas as pd
        df_a = pd.DataFrame(
            audits,
            columns=["ID", "Timestamp", "Actor", "Action", "Entity", "Entity ID", "Before", "After"],
        )
        st.dataframe(df_a, use_container_width=True, hide_index=True)
    else:
        st.info("No audit entries yet.")

# ── Footer ───────────────────────────────────────────────────────────
st.divider()
st.caption(
    "CloseDesk — Governed UPI Reconciliation | "
    "ExaThon India 2026 | "
    "All data is synthetic. Not real NPCI/bank data."
)
