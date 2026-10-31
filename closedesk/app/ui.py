"""CloseDesk investigator UI. Five screens, real Exasol state only."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import os
import re
import secrets
import time
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import pyexasol
import streamlit as st
import yaml
from dotenv import dotenv_values

from closedesk.agent.policy import gate, load_policy
from closedesk.agent.propose import ACTION_MAP, propose_all
from closedesk.engine.run import STAGES, _prepare_sql, _sanitise_run_id
from closedesk.eval.score import score
from closedesk.generator.build import (
    GATEWAYS,
    LEDGER_HEADERS,
    MERCHANT_HEADERS,
    NPCI_HEADERS,
    generate,
)
from closedesk.loader.load import load

ROOT = Path(__file__).resolve().parents[2]

BACKGROUND = "#0A0E17"
SURFACE = "#111827"
SURFACE_ELEVATED = "#1A2332"
BORDER = "#1E293B"
BORDER_FOCUS = "#334155"
TEXT_PRIMARY = "#F1F5F9"
TEXT_SECONDARY = "#94A3B8"
TEXT_MUTED = "#475569"
ACCENT_GREEN = "#10B981"
ACCENT_RED = "#EF4444"
ACCENT_AMBER = "#F59E0B"
ACCENT_BLUE = "#3B82F6"
ACCENT_CYAN = "#06B6D4"
RUPEE_GREEN = "#059669"
RUPEE_RED = "#DC2626"
CHART_PALETTE = [
    "#3B82F6",
    "#10B981",
    "#F59E0B",
    "#EF4444",
    "#8B5CF6",
    "#EC4899",
    "#06B6D4",
]
MONO = "'SF Mono', 'Fira Code', 'Consolas', monospace"

SCALE_ROWS = {"10K": 10_000, "100K": 100_000, "1M": 1_000_000}
SCALE_SECONDS = {"10K": 0.5, "100K": 3, "1M": 8}
BREAK_STAGES = {"classify", "orphans", "duplicates", "status_mismatch"}
STAGE_LABELS = {
    "generate": "Generate",
    "schema": "Schema",
    "load": "Load",
    "exact": "Exact match",
    "tolerance": "Tolerance",
    "many_to_one": "Many-to-one",
    "classify": "Classify",
    "orphans": "Orphans",
    "duplicates": "Duplicates",
    "status_mismatch": "Status mismatch",
    "root_causes": "Root causes",
    "priority": "Priority",
    "agent": "Proposals",
    "eval": "Evaluate",
}
NAV = [
    ("pipeline", "Pipeline", "Generate a day and watch reconciliation"),
    ("investigate", "Investigate", "Compare one payment across three systems"),
    ("inject", "Inject & Detect", "Plant a break and see it caught"),
    ("exceptions", "Exceptions", "Approve or reject a proposed fix"),
    ("analytics", "Analytics", "Funnel, causes, and the audit trail"),
]
INJECT_TYPES = [
    ("Duplicate ledger entry", "duplicate_ledger"),
    ("Amount mismatch (merchant)", "amount_mismatch"),
    ("Failed but debited", "failed_but_debited"),
    ("Missing NPCI settlement", "missing_settlement"),
    ("Reversal not posted", "reversal_not_posted"),
]
ALL_STEPS: list[tuple[str, str | None, str | None]] = [
    ("generate", None, None),
    ("schema", None, None),
    ("load", None, None),
]
ALL_STEPS.extend((name, fname, table) for fname, name, table in STAGES)
ALL_STEPS.extend([("agent", None, None), ("eval", None, None)])
UPLOAD_STEPS = [step for step in ALL_STEPS if step[0] not in ("generate", "eval")]
UPLOAD_DIR = ROOT / "data" / "upload"
SAMPLES_DIR = ROOT / "samples"
UPLOAD_FILES = [
    ("npci", "NPCI settlement", "npci_settlement.csv", NPCI_HEADERS),
    ("ledger", "Bank ledger", "bank_ledger.csv", LEDGER_HEADERS),
    ("merchant", "Merchant records", "merchant_records.csv", MERCHANT_HEADERS),
]


def current_steps() -> list[tuple[str, str | None, str | None]]:
    if st.session_state.get("pipeline_mode") == "upload":
        return UPLOAD_STEPS
    return ALL_STEPS


def fmt_inr(amount: float) -> str:
    """Format rupees with Indian grouping and two decimals."""
    value = float(amount)
    sign = "-" if value < 0 else ""
    whole, frac = f"{abs(value):.2f}".split(".")
    if len(whole) <= 3:
        grouped = whole
    else:
        head, tail = whole[:-3], whole[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.append(head[-2:])
            head = head[:-2]
        if head:
            parts.append(head)
        grouped = ",".join(reversed(parts)) + "," + tail
    return f"{sign}₹{grouped}.{frac}"


def fmt_inr_short(amount: float) -> str:
    """Compact rupees for KPI headers. Crore, then lakh, then exact."""
    value = float(amount)
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if magnitude >= 1_00_00_000:
        return f"{sign}₹{magnitude / 1_00_00_000:.2f} Cr"
    if magnitude >= 1_00_000:
        return f"{sign}₹{magnitude / 1_00_000:.2f} L"
    return fmt_inr(value)


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def sql_text(value: str, limit: int = 4000) -> str:
    return value.replace("'", "''")[:limit]


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + sql_text(str(value)) + "'"


def safe_ref(value: str) -> str | None:
    cleaned = value.strip()
    if re.fullmatch(r"[A-Za-z0-9]+", cleaned):
        return cleaned
    return None


def widget_id(prefix: str, raw: str) -> str:
    return prefix + "_" + re.sub(r"[^A-Za-z0-9]", "", raw)


def pill(text: str, color: str) -> str:
    return (
        f'<span style="display:inline-block;padding:2px 6px;margin:2px 4px 2px 0;'
        f"font-family:{MONO};font-size:0.7rem;letter-spacing:0.04em;"
        f'color:{color};background:{color}26;border:1px solid {color};">'
        f"{esc(text)}</span>"
    )


def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{ background: {BACKGROUND}; color: {TEXT_PRIMARY}; }}
        [data-testid="stHeader"] {{ background: transparent; }}
        [data-testid="stSidebar"] {{
            background: {SURFACE};
            border-right: 1px solid {BORDER};
        }}
        [data-testid="stSidebar"] .stButton > button {{
            width: 100%;
            text-align: left;
            border-radius: 0;
            background: transparent;
            color: {TEXT_SECONDARY};
            border: none;
            border-left: 3px solid transparent;
            padding: 0.45rem 0.75rem;
            font-weight: 600;
        }}
        [data-testid="stSidebar"] .stButton > button[kind="primary"] {{
            background: {SURFACE_ELEVATED};
            color: {TEXT_PRIMARY};
            border-left: 3px solid {ACCENT_BLUE};
        }}
        [data-testid="stSidebar"] [data-testid="stCaption"] {{
            margin-top: -0.85rem;
            margin-bottom: 0.35rem;
            color: {TEXT_MUTED};
            font-size: 0.75rem;
        }}
        .stButton > button {{
            border-radius: 0;
            border: 1px solid {BORDER_FOCUS};
            background: {SURFACE};
            color: {TEXT_PRIMARY};
            font-weight: 600;
        }}
        .stButton > button[kind="primary"] {{
            background: {ACCENT_BLUE};
            border-color: {ACCENT_BLUE};
            color: #ffffff;
        }}
        .st-key-generate_btn button, .st-key-inject_btn button {{
            width: 100%;
            font-size: 1.125rem;
            font-weight: 600;
            padding: 0.7rem 1rem;
        }}
        .st-key-inject_btn button {{
            background: {ACCENT_RED} !important;
            border-color: {ACCENT_RED} !important;
            color: #ffffff !important;
        }}
        [class*="st-key-ok_"] button {{
            background: transparent !important;
            color: {ACCENT_GREEN} !important;
            border: 1px solid {ACCENT_GREEN} !important;
        }}
        [class*="st-key-no_"] button {{
            background: transparent !important;
            color: {ACCENT_RED} !important;
            border: 1px solid {ACCENT_RED} !important;
        }}
        .stTabs [data-baseweb="tab-list"] {{
            background: {SURFACE};
            border-bottom: 1px solid {BORDER};
            gap: 0;
        }}
        .stTabs [data-baseweb="tab"] {{
            background: transparent;
            color: {TEXT_SECONDARY};
            border-radius: 0;
        }}
        [data-testid="stMetric"] {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            padding: 0.5rem 0.75rem;
        }}
        div[data-testid="stDataFrame"] {{ border: 1px solid {BORDER}; }}
        .stSelectbox label, .stNumberInput label, .stCheckbox label {{
            color: {TEXT_SECONDARY};
            font-size: 0.75rem;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }}
        ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
        ::-webkit-scrollbar-thumb {{ background: {BORDER_FOCUS}; }}
        ::-webkit-scrollbar-track {{ background: {BACKGROUND}; }}
        .block-container {{ padding-top: 1.25rem; max-width: 100%; }}
        @keyframes cd-pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.4; }}
        }}
        .cd-running {{
            animation: cd-pulse 1.5s ease-in-out infinite;
            color: {ACCENT_BLUE};
            font-family: {MONO};
            font-weight: 600;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_state() -> None:
    defaults: dict[str, object] = {
        "screen": "pipeline",
        "run_id": None,
        "run_bootstrapped": False,
        "pipeline_running": False,
        "pipeline_index": 0,
        "pipeline_log": [],
        "pipeline_error": None,
        "pipeline_done": False,
        "pipeline_hydrated": False,
        "scenario_path": "",
        "injected_breaks": [],
        "injection_result": None,
        "inj_sig": None,
        "inj_plan": None,
        "eval_result": None,
        "scale": "100K",
        "pipeline_mode": "generate",
        "source_tab": "generate",
        "upload_error": None,
        "ex_offset": 0,
        "ex_sig": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    scenario = load_scenario()
    for name in scenario["breaks"]:
        key = f"brk_{name}"
        if key not in st.session_state:
            st.session_state[key] = True


def load_scenario() -> dict:
    return yaml.safe_load((ROOT / "config" / "scenario.yaml").read_text())


@st.cache_resource
def get_connection() -> pyexasol.ExaConnection:
    env = dotenv_values(ROOT / ".env")
    if not env.get("EXA_PASSWORD"):
        raise RuntimeError(
            "EXA_PASSWORD is empty. Copy .env.example to .env and set the Exasol password."
        )
    return pyexasol.connect(
        dsn=env.get("EXA_DSN", "localhost:8563"),
        user=env.get("EXA_USER", "sys"),
        password=env.get("EXA_PASSWORD", ""),
        schema=env.get("EXA_SCHEMA", "CLOSEDESK"),
        compression=True,
        websocket_sslopt={"cert_reqs": 0},
    )


def connect_fresh() -> pyexasol.ExaConnection:
    """Connection without a default schema, used while CLOSEDESK is recreated."""
    env = dotenv_values(ROOT / ".env")
    return pyexasol.connect(
        dsn=env.get("EXA_DSN", "localhost:8563"),
        user=env.get("EXA_USER", "sys"),
        password=env.get("EXA_PASSWORD", ""),
        compression=True,
        websocket_sslopt={"cert_reqs": 0},
    )


def acquire_connection() -> tuple[pyexasol.ExaConnection | None, str | None]:
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        return conn, None
    except (pyexasol.ExaError, RuntimeError, OSError):
        get_connection.clear()
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        return conn, None
    except (pyexasol.ExaError, RuntimeError, OSError) as exc:
        return None, str(exc)


def bootstrap_run(conn: pyexasol.ExaConnection) -> None:
    if st.session_state.run_bootstrapped:
        return
    st.session_state.run_bootstrapped = True
    if st.session_state.run_id:
        return
    try:
        rid = conn.execute(
            "SELECT run_id FROM match_stage_log ORDER BY started_at DESC LIMIT 1"
        ).fetchval()
    except pyexasol.ExaQueryError:
        rid = None
    st.session_state.run_id = rid


def q_all(conn: pyexasol.ExaConnection, sql: str) -> list[tuple]:
    return list(conn.execute(sql).fetchall())


def q_val(conn: pyexasol.ExaConnection, sql: str) -> object:
    return conn.execute(sql).fetchval()


def show_query_error(exc: pyexasol.ExaError) -> None:
    st.markdown(
        f'<div style="color:{ACCENT_RED};font-family:{MONO};font-size:0.8125rem;'
        f'white-space:pre-wrap;">{esc(exc)}</div>',
        unsafe_allow_html=True,
    )


def run_stats(conn: pyexasol.ExaConnection, run_id: str) -> dict[str, float]:
    rid = sql_text(run_id)
    npci = int(q_val(conn, "SELECT COUNT(*) FROM npci_settlement") or 0)
    matched = int(q_val(conn, f"SELECT COUNT(*) FROM matches WHERE run_id = '{rid}'") or 0)
    breaks = int(q_val(conn, f"SELECT COUNT(*) FROM breaks WHERE run_id = '{rid}'") or 0)
    causes = int(q_val(conn, f"SELECT COUNT(*) FROM root_causes WHERE run_id = '{rid}'") or 0)
    total_inr = float(q_val(conn, "SELECT COALESCE(SUM(amount_inr), 0) FROM npci_settlement") or 0)
    matched_inr = float(
        q_val(
            conn,
            f"SELECT COALESCE(SUM(amount_inr), 0) FROM matches WHERE run_id = '{rid}'",
        )
        or 0
    )
    return {
        "npci": npci,
        "matched": matched,
        "breaks": breaks,
        "causes": causes,
        "total_inr": total_inr,
        "matched_inr": matched_inr,
        "rate": (matched / npci * 100) if npci else 0.0,
    }


def source_counts(conn: pyexasol.ExaConnection) -> dict[str, int] | None:
    try:
        return {
            "NPCI": int(q_val(conn, "SELECT COUNT(*) FROM npci_settlement") or 0),
            "Ledger": int(q_val(conn, "SELECT COUNT(*) FROM bank_ledger") or 0),
            "Merchant": int(q_val(conn, "SELECT COUNT(*) FROM merchant_records") or 0),
        }
    except pyexasol.ExaQueryError:
        return None


def render_sidebar(conn: pyexasol.ExaConnection | None, error: str | None) -> None:
    st.sidebar.markdown(
        f"""
        <div style="font-family:{MONO};font-size:1.05rem;font-weight:600;
        letter-spacing:0.08em;color:{TEXT_PRIMARY};">CLOSEDESK ·</div>
        <div style="font-size:0.75rem;font-weight:500;letter-spacing:0.05em;
        text-transform:uppercase;color:{TEXT_SECONDARY};margin-top:2px;">
        UPI Reconciliation</div>
        """,
        unsafe_allow_html=True,
    )
    run_id = st.session_state.get("run_id")
    if run_id:
        st.sidebar.markdown(
            f'<div style="font-family:{MONO};color:{TEXT_MUTED};font-size:0.75rem;'
            f'margin-top:0.35rem;">{esc(run_id)}</div>',
            unsafe_allow_html=True,
        )
    st.sidebar.markdown(
        f'<hr style="border:none;border-top:1px solid {BORDER};margin:0.75rem 0;">',
        unsafe_allow_html=True,
    )
    for key, label, desc in NAV:
        kind = "primary" if st.session_state.screen == key else "secondary"
        if st.sidebar.button(label, key=f"nav_{key}", type=kind, width="stretch"):
            st.session_state.screen = key
            st.rerun()
        st.sidebar.caption(desc)

    st.sidebar.markdown(
        f'<hr style="border:none;border-top:1px solid {BORDER};margin:0.75rem 0;">',
        unsafe_allow_html=True,
    )
    dot = ACCENT_GREEN if conn is not None and error is None else ACCENT_RED
    st.sidebar.markdown(
        f'<div style="font-size:0.8125rem;color:{TEXT_SECONDARY};">'
        f'<span style="color:{dot};">●</span> Exasol Personal</div>',
        unsafe_allow_html=True,
    )
    counts = source_counts(conn) if conn is not None else None
    if counts:
        lines = "".join(
            f'<div style="font-family:{MONO};font-size:0.75rem;color:{TEXT_SECONDARY};">'
            f"{esc(name)} {count:,}</div>"
            for name, count in counts.items()
        )
        st.sidebar.markdown(lines, unsafe_allow_html=True)
    st.sidebar.markdown(
        f'<div style="font-size:0.75rem;color:{TEXT_MUTED};margin-top:0.5rem;">'
        "Synthetic data only</div>",
        unsafe_allow_html=True,
    )


def render_conn_error(error: str | None) -> None:
    st.markdown(
        f"""
        <div style="border:1px solid {ACCENT_RED};background:{SURFACE};padding:1.5rem;">
          <div style="font-size:1.5rem;font-weight:600;color:{TEXT_PRIMARY};">
            Cannot connect to Exasol Personal.
          </div>
          <div style="color:{TEXT_SECONDARY};margin-top:0.5rem;">
            Is the VM running? Check <span style="font-family:{MONO};">exasol status</span>.
          </div>
          <div style="color:{ACCENT_RED};font-family:{MONO};font-size:0.8125rem;
          margin-top:0.75rem;white-space:pre-wrap;">{esc(error or "")}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Retry connection", type="primary"):
        get_connection.clear()
        st.rerun()


def empty_run(message: str) -> None:
    st.markdown(
        f"""
        <div style="border:1px solid {BORDER};background:{SURFACE};padding:1.5rem;">
          <div style="font-size:1.125rem;font-weight:600;color:{TEXT_PRIMARY};">{esc(message)}</div>
          <div style="color:{TEXT_SECONDARY};margin-top:0.4rem;">
            Run the pipeline to load a synthetic settlement day into Exasol.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open Pipeline", type="primary"):
        st.session_state.screen = "pipeline"
        st.rerun()


def heading(text: str, size: str = "1.5rem") -> None:
    st.markdown(
        f'<div style="font-size:{size};font-weight:600;letter-spacing:-0.015em;'
        f'color:{TEXT_PRIMARY};margin:0.25rem 0 0.75rem;">{esc(text)}</div>',
        unsafe_allow_html=True,
    )


def label(text: str) -> str:
    return (
        f'<div style="font-size:0.75rem;font-weight:500;letter-spacing:0.05em;'
        f'text-transform:uppercase;color:{TEXT_SECONDARY};">{esc(text)}</div>'
    )


# --- Pipeline -----------------------------------------------------------------


def start_pipeline() -> None:
    cfg = load_scenario()
    for name in cfg["breaks"]:
        if not st.session_state.get(f"brk_{name}", True):
            cfg["breaks"][name] = 0.0
    cfg["rows_per_source"] = SCALE_ROWS[st.session_state.scale]
    out = ROOT / "data"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "ui_scenario.yaml"
    path.write_text(yaml.safe_dump(cfg))
    run_id = _sanitise_run_id(f"R-{cfg['iso_date']}-{secrets.token_hex(3)}")
    begin_run(run_id, "generate")
    st.session_state.scenario_path = str(path)


def begin_run(run_id: str, mode: str) -> None:
    st.session_state.run_id = run_id
    st.session_state.pipeline_mode = mode
    st.session_state.pipeline_running = True
    st.session_state.pipeline_index = 0
    st.session_state.pipeline_log = []
    st.session_state.pipeline_error = None
    st.session_state.pipeline_done = False
    st.session_state.pipeline_hydrated = True
    st.session_state.eval_result = None
    st.session_state.injection_result = None
    st.session_state.injected_breaks = []


def append_log(name: str, rows: int, rupees: float, seconds: float) -> None:
    st.session_state.pipeline_log.append(
        {"name": name, "rows": rows, "rupees": rupees, "seconds": seconds}
    )


def apply_schema() -> None:
    raw = (ROOT / "sql" / "00_schema.sql").read_text()
    lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
    conn = connect_fresh()
    try:
        for stmt in "\n".join(lines).split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
    finally:
        conn.close()
    get_connection.clear()


def stage_counts(
    conn: pyexasol.ExaConnection, run_id: str, stage_name: str, result_table: str
) -> tuple[int, float]:
    rid = sql_text(run_id)
    if stage_name in ("exact", "tolerance", "many_to_one"):
        sql = (
            f"SELECT COUNT(*), COALESCE(SUM(amount_inr), 0) FROM {result_table} "
            f"WHERE run_id = '{rid}' AND stage = '{stage_name}'"
        )
    elif stage_name in BREAK_STAGES:
        sql = f"SELECT COUNT(*), COALESCE(SUM(amount_inr), 0) FROM breaks WHERE run_id = '{rid}'"
    elif stage_name == "root_causes":
        sql = (
            f"SELECT COUNT(*), COALESCE(SUM(rupees_at_risk), 0) FROM root_causes "
            f"WHERE run_id = '{rid}'"
        )
    elif stage_name == "priority":
        sql = (
            f"SELECT COUNT(*), COALESCE(SUM(rupees_at_risk), 0) FROM breaks WHERE run_id = '{rid}'"
        )
    else:
        return 0, 0.0
    row = conn.execute(sql).fetchone()
    return int(row[0]), float(row[1])


def run_sql_stage(
    conn: pyexasol.ExaConnection, run_id: str, sql_file: str, stage_name: str, result_table: str
) -> tuple[int, float, float]:
    scenario_path = Path(st.session_state.scenario_path or ROOT / "config" / "scenario.yaml")
    scenario = yaml.safe_load(scenario_path.read_text())
    policy = yaml.safe_load((ROOT / "config" / "policy.yaml").read_text())
    raw = (ROOT / "sql" / sql_file).read_text()
    stmts = _prepare_sql(
        raw,
        run_id,
        float(scenario["tolerance"]["amount_inr"]),
        int(scenario["tolerance"]["time_seconds"]),
        float(policy["compensation"]["rupees_per_day"]),
    )
    t0 = time.perf_counter()
    for stmt in stmts:
        conn.execute(stmt)
    elapsed = time.perf_counter() - t0
    count, rupees = stage_counts(conn, run_id, stage_name, result_table)
    rid = sql_text(run_id)
    conn.execute(f"DELETE FROM match_stage_log WHERE run_id = '{rid}' AND stage = '{stage_name}'")
    conn.execute(
        "INSERT INTO match_stage_log "
        "(run_id, stage, started_at, elapsed_ms, rows_in, rows_matched, rupees_matched) "
        f"VALUES ('{rid}', '{stage_name}', NOW(), {int(elapsed * 1000)}, 0, {count}, {rupees})"
    )
    return count, rupees, elapsed


def execute_step(
    conn: pyexasol.ExaConnection, name: str, sql_file: str | None, table: str | None
) -> None:
    run_id = st.session_state.run_id
    t0 = time.perf_counter()
    if name == "generate":
        scenario_path = Path(st.session_state.scenario_path)
        generate(scenario_path=scenario_path, out_dir=ROOT / "data")
        cfg = yaml.safe_load(scenario_path.read_text())
        append_log(name, int(cfg["rows_per_source"]), 0.0, time.perf_counter() - t0)
        return
    if name == "schema":
        apply_schema()
        append_log(name, 0, 0.0, time.perf_counter() - t0)
        return
    if name == "load":
        source = UPLOAD_DIR if st.session_state.pipeline_mode == "upload" else ROOT / "data"
        load(data_dir=source, env_path=ROOT / ".env")
        get_connection.clear()
        fresh = get_connection()
        rows = int(q_val(fresh, "SELECT COUNT(*) FROM npci_settlement") or 0)
        rupees = float(
            q_val(fresh, "SELECT COALESCE(SUM(amount_inr), 0) FROM npci_settlement") or 0
        )
        append_log(name, rows, rupees, time.perf_counter() - t0)
        return
    if name == "agent":
        stats = propose_all(
            run_id, env_path=ROOT / ".env", policy_path=ROOT / "config" / "policy.yaml"
        )
        append_log(name, int(stats["total"]), 0.0, time.perf_counter() - t0)
        return
    if name == "eval":
        result = score(run_id, env_path=ROOT / ".env")
        st.session_state.eval_result = result
        append_log(name, int(result["total_answer_key"]), 0.0, time.perf_counter() - t0)
        return
    if sql_file and table:
        count, rupees, elapsed = run_sql_stage(conn, run_id, sql_file, name, table)
        append_log(name, count, rupees, elapsed)


def advance_pipeline(conn: pyexasol.ExaConnection) -> None:
    steps = current_steps()
    index = int(st.session_state.pipeline_index)
    if index >= len(steps):
        st.session_state.pipeline_running = False
        st.session_state.pipeline_done = True
        st.rerun()
        return
    name, sql_file, table = steps[index]
    try:
        live = get_connection() if name != "schema" else conn
        execute_step(live, name, sql_file, table)
    except pyexasol.ExaError as exc:
        st.session_state.pipeline_running = False
        st.session_state.pipeline_error = str(exc)
        st.rerun()
        return
    st.session_state.pipeline_index = index + 1
    if st.session_state.pipeline_index >= len(steps):
        st.session_state.pipeline_running = False
        st.session_state.pipeline_done = True
    st.rerun()


def hydrate_pipeline(conn: pyexasol.ExaConnection) -> None:
    if st.session_state.pipeline_hydrated or st.session_state.pipeline_running:
        return
    if st.session_state.pipeline_log or not st.session_state.run_id:
        st.session_state.pipeline_hydrated = True
        return
    rid = sql_text(str(st.session_state.run_id))
    try:
        rows = q_all(
            conn,
            "SELECT stage, rows_matched, rupees_matched, elapsed_ms "
            "FROM match_stage_log "
            f"WHERE run_id = '{rid}' ORDER BY started_at",
        )
    except pyexasol.ExaQueryError:
        rows = []
    st.session_state.pipeline_log = [
        {
            "name": row[0],
            "rows": int(row[1]),
            "rupees": float(row[2]),
            "seconds": float(row[3]) / 1000,
        }
        for row in rows
    ]
    st.session_state.pipeline_hydrated = True
    if st.session_state.pipeline_log:
        st.session_state.pipeline_done = True
        st.session_state.pipeline_index = len(current_steps())


def render_meter(conn: pyexasol.ExaConnection) -> None:
    total = matched = 0.0
    if st.session_state.run_id:
        try:
            stats = run_stats(conn, str(st.session_state.run_id))
            total = stats["total_inr"]
            matched = min(stats["matched_inr"], total) if total else 0.0
        except pyexasol.ExaQueryError as exc:
            show_query_error(exc)
    at_risk = max(total - matched, 0.0)
    pct = (matched / total * 100) if total else 0.0
    st.markdown(
        f"""
        <div style="background:{SURFACE};border:1px solid {BORDER};padding:0.9rem 1rem;margin-bottom:1rem;">
          <div style="display:flex;justify-content:space-between;gap:1rem;">
            <div style="color:{RUPEE_GREEN};font-family:{MONO};font-size:1.125rem;font-weight:600;">
              {esc(fmt_inr(matched))} reconciled
            </div>
            <div style="color:{RUPEE_RED};font-family:{MONO};font-size:1.125rem;font-weight:600;">
              {esc(fmt_inr(at_risk))} at risk
            </div>
          </div>
          <div style="display:flex;height:28px;width:100%;margin-top:0.6rem;background:{BACKGROUND};">
            <div style="width:{pct:.4f}%;background:{RUPEE_GREEN};"></div>
            <div style="width:{100 - pct:.4f}%;background:{RUPEE_RED};"></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stage_table() -> None:
    log = {entry["name"]: entry for entry in st.session_state.pipeline_log}
    running = bool(st.session_state.pipeline_running)
    index = int(st.session_state.pipeline_index)
    if running:
        names = [step[0] for step in current_steps()]
    else:
        names = [entry["name"] for entry in st.session_state.pipeline_log]
    rows_html = []
    for pos, name in enumerate(names):
        entry = log.get(name)
        if entry:
            if name in BREAK_STAGES and entry["rows"]:
                status = (
                    f'<span style="color:{ACCENT_RED};font-family:{MONO};">{entry["rows"]:,}</span>'
                )
            else:
                status = f'<span style="color:{ACCENT_GREEN};">✓</span>'
            color = TEXT_PRIMARY
            row_txt = f"{entry['rows']:,}"
            rupee_txt = fmt_inr(entry["rupees"]) if entry["rupees"] else "—"
            time_txt = f"{entry['seconds']:.2f}s"
        elif running and pos == index:
            status = '<span class="cd-running">RUNNING</span>'
            color = ACCENT_BLUE
            row_txt = rupee_txt = time_txt = "—"
        else:
            status = f'<span style="color:{TEXT_MUTED};">—</span>'
            color = TEXT_MUTED
            row_txt = rupee_txt = time_txt = "—"
        rows_html.append(
            f'<tr style="color:{color};border-bottom:1px solid {BORDER};">'
            f'<td style="padding:0.45rem 0.3rem;">{esc(STAGE_LABELS.get(name, name))}</td>'
            f"<td>{status}</td>"
            f'<td style="text-align:right;font-family:{MONO};">{row_txt}</td>'
            f'<td style="text-align:right;font-family:{MONO};">{esc(rupee_txt)}</td>'
            f'<td style="text-align:right;font-family:{MONO};">{time_txt}</td></tr>'
        )
    st.markdown(
        f"""
        <table style="width:100%;border-collapse:collapse;font-size:0.8125rem;">
          <thead>
            <tr style="color:{TEXT_SECONDARY};font-size:0.75rem;letter-spacing:0.05em;
            text-transform:uppercase;border-bottom:1px solid {BORDER};">
              <th style="text-align:left;padding:0.4rem 0.3rem;">Stage</th>
              <th style="text-align:left;">Status</th>
              <th style="text-align:right;">Rows</th>
              <th style="text-align:right;">₹ Value</th>
              <th style="text-align:right;">Time</th>
            </tr>
          </thead>
          <tbody>{"".join(rows_html)}</tbody>
        </table>
        """,
        unsafe_allow_html=True,
    )


def render_summary(conn: pyexasol.ExaConnection) -> None:
    try:
        stats = run_stats(conn, str(st.session_state.run_id))
    except pyexasol.ExaQueryError as exc:
        show_query_error(exc)
        return
    rate = stats["rate"]
    if rate > 95:
        rate_color = ACCENT_GREEN
    elif rate >= 90:
        rate_color = ACCENT_AMBER
    else:
        rate_color = ACCENT_RED
    wall = sum(float(entry["seconds"]) for entry in st.session_state.pipeline_log)
    boxes = [
        ("Match rate", f"{rate:.1f}%", rate_color),
        ("Breaks", f"{int(stats['breaks']):,}", ACCENT_RED),
        ("Root causes", f"{int(stats['causes']):,}", ACCENT_BLUE),
        ("Wall time", f"{wall:.2f}s", TEXT_PRIMARY),
    ]
    cells = []
    for title, value, color in boxes:
        cells.append(
            f'<div style="background:{SURFACE_ELEVATED};border:1px solid {BORDER};padding:0.75rem 1rem;">'
            f"{label(title)}"
            f'<div style="font-family:{MONO};font-size:1.75rem;font-weight:700;color:{color};">'
            f"{esc(value)}</div></div>"
        )
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));'
        f'gap:0.75rem;margin-top:1rem;">{"".join(cells)}</div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    if left.button("→ View Exceptions", width="stretch"):
        st.session_state.screen = "exceptions"
        st.rerun()
    if right.button("→ Investigate Transaction", width="stretch"):
        st.session_state.screen = "investigate"
        st.rerun()


def render_config() -> None:
    scenario = load_scenario()
    names = list(scenario["breaks"].keys())
    heading("Pipeline configuration")
    left, right = st.columns([3, 2])
    with left:
        st.markdown(label("Scale"), unsafe_allow_html=True)
        cols = st.columns(3)
        for col, scale in zip(cols, SCALE_ROWS, strict=True):
            kind = "primary" if st.session_state.scale == scale else "secondary"
            if col.button(scale, key=f"scale_{scale}", type=kind, width="stretch"):
                st.session_state.scale = scale
                st.rerun()
        st.markdown(
            f'<div style="margin-top:1rem;">{label("Planted breaks")}</div>',
            unsafe_allow_html=True,
        )
        for row_i in range(4):
            pair = st.columns(2)
            for col_i in range(2):
                idx = row_i * 2 + col_i
                if idx >= len(names):
                    continue
                name = names[idx]
                frac = float(scenario["breaks"][name])
                pair[col_i].checkbox(
                    f"{name.replace('_', ' ')}  {frac * 100:.1f}%",
                    key=f"brk_{name}",
                )
    selected = [name for name in names if st.session_state.get(f"brk_{name}", True)]
    rows = SCALE_ROWS[st.session_state.scale]
    expected = int(rows * sum(float(scenario["breaks"][name]) for name in selected))
    with right:
        st.markdown(
            f"""
            <div style="background:{SURFACE};border:1px solid {BORDER};padding:1rem;">
              {label("This run")}
              <div style="font-family:{MONO};color:{TEXT_PRIMARY};margin-top:0.6rem;">
                Estimated rows per source: {rows:,}<br>
                Break types enabled: {len(selected)}/7<br>
                Expected breaks: ~{expected:,}<br>
                Estimated time: ~{SCALE_SECONDS[st.session_state.scale]:.1f}s
              </div>
              <div style="color:{TEXT_MUTED};font-size:0.8125rem;margin-top:0.75rem;">
                Replaces the settlement day currently loaded in Exasol.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    if st.button("GENERATE & DETECT", key="generate_btn", type="primary", width="stretch"):
        start_pipeline()
        st.rerun()


def validate_csv(data: bytes, headers: list[str]) -> tuple[int, str | None]:
    """Check a settlement CSV before it reaches Exasol. Returns (rows, error)."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return 0, "File is not UTF-8 text."
    reader = csv.reader(io.StringIO(text))
    found = [col.strip().lower() for col in next(reader, [])]
    if found != headers:
        return 0, "Header must be: " + ",".join(headers)
    amount_col = headers.index("amount_inr")
    seen: set[str] = set()
    rows = 0
    for line_no, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) != len(headers):
            return rows, f"Line {line_no}: expected {len(headers)} columns, found {len(row)}."
        try:
            float(row[amount_col])
        except ValueError:
            return rows, f"Line {line_no}: amount_inr '{row[amount_col]}' is not a number."
        key = row[0].strip()
        if not key:
            return rows, f"Line {line_no}: {headers[0]} is empty."
        if key in seen:
            return rows, f"Line {line_no}: duplicate {headers[0]} '{key}'."
        seen.add(key)
        rows += 1
    if rows == 0:
        return 0, "File has a header but no rows."
    return rows, None


def upload_check(key: str, uploaded: object, headers: list[str]) -> tuple[int, str | None]:
    checks: dict = st.session_state.setdefault("upload_checks", {})
    file_id = getattr(uploaded, "file_id", None) or getattr(uploaded, "name", "")
    cached = checks.get(key)
    if cached and cached[0] == file_id:
        return cached[1], cached[2]
    rows, error = validate_csv(uploaded.getvalue(), headers)  # type: ignore[attr-defined]
    checks[key] = (file_id, rows, error)
    return rows, error


def start_upload_run(files: dict[str, object]) -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for stale in UPLOAD_DIR.glob("*.csv"):
        stale.unlink()
    for key, _title, filename, _headers in UPLOAD_FILES:
        (UPLOAD_DIR / filename).write_bytes(files[key].getvalue())  # type: ignore[attr-defined]
    begin_run(_sanitise_run_id(f"R-UPLOAD-{secrets.token_hex(3)}"), "upload")
    st.session_state.scenario_path = ""


def render_upload() -> None:
    heading("Upload settlement files")
    st.markdown(
        f'<div style="color:{TEXT_SECONDARY};margin-bottom:0.8rem;">'
        "Drop the day's three files. Each is checked before it is loaded into Exasol, "
        "then the same matching pipeline runs on it. Uploaded files have no answer key, "
        "so accuracy scoring is not available for this run.</div>",
        unsafe_allow_html=True,
    )
    files: dict[str, object] = {}
    ready = True
    cols = st.columns(3)
    for col, (key, title, filename, headers) in zip(cols, UPLOAD_FILES, strict=True):
        with col:
            st.markdown(label(title), unsafe_allow_html=True)
            st.markdown(
                f'<div style="font-family:{MONO};font-size:0.7rem;color:{TEXT_MUTED};'
                f'word-break:break-all;margin-bottom:0.4rem;">{esc(",".join(headers))}</div>',
                unsafe_allow_html=True,
            )
            uploaded = st.file_uploader(
                title, type=["csv"], key=f"up_{key}", label_visibility="collapsed"
            )
            sample = SAMPLES_DIR / filename
            if sample.exists():
                st.download_button(
                    f"Sample {filename}",
                    sample.read_bytes(),
                    file_name=filename,
                    mime="text/csv",
                    key=f"sample_{key}",
                    width="stretch",
                )
            if uploaded is None:
                ready = False
                continue
            rows, error = upload_check(key, uploaded, headers)
            if error:
                ready = False
                st.markdown(
                    f'<div style="color:{ACCENT_RED};font-size:0.8125rem;">{esc(error)}</div>',
                    unsafe_allow_html=True,
                )
            else:
                files[key] = uploaded
                st.markdown(
                    f'<div style="color:{ACCENT_GREEN};font-family:{MONO};font-size:0.8125rem;">'
                    f"✓ {rows:,} rows</div>",
                    unsafe_allow_html=True,
                )
    st.markdown(
        f'<div style="color:{TEXT_MUTED};font-size:0.8125rem;margin:0.5rem 0;">'
        "Replaces the settlement day currently loaded in Exasol.</div>",
        unsafe_allow_html=True,
    )
    if st.button(
        "LOAD & RECONCILE",
        key="generate_btn",
        type="primary",
        width="stretch",
        disabled=not ready,
    ):
        start_upload_run(files)
        st.rerun()


def render_source_switch() -> None:
    left, right = st.columns(2)
    for col, key, text in (
        (left, "generate", "Generate a synthetic day"),
        (right, "upload", "Upload three files"),
    ):
        kind = "primary" if st.session_state.source_tab == key else "secondary"
        if col.button(text, key=f"src_{key}", type=kind, width="stretch"):
            st.session_state.source_tab = key
            st.rerun()


def screen_pipeline(conn: pyexasol.ExaConnection) -> None:
    hydrate_pipeline(conn)
    if st.session_state.pipeline_error:
        st.markdown(
            f'<div style="color:{ACCENT_RED};font-family:{MONO};font-size:0.8125rem;'
            f'white-space:pre-wrap;margin-bottom:0.75rem;">'
            f"{esc(st.session_state.pipeline_error)}</div>",
            unsafe_allow_html=True,
        )
    show_run = bool(st.session_state.pipeline_running or st.session_state.pipeline_log)
    if show_run:
        render_meter(conn)
        render_stage_table()
        if st.session_state.pipeline_done and not st.session_state.pipeline_running:
            render_summary(conn)
    if not st.session_state.pipeline_running:
        if show_run:
            st.markdown(
                f'<div style="margin-top:1.5rem;">{label("New run")}</div>',
                unsafe_allow_html=True,
            )
        render_source_switch()
        if st.session_state.source_tab == "upload":
            render_upload()
        else:
            render_config()
    else:
        advance_pipeline(conn)


# --- Investigator -------------------------------------------------------------


def as_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    text = str(value)[:26]
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def fetch_dicts(
    conn: pyexasol.ExaConnection, sql: str, columns: list[str]
) -> list[dict[str, object]]:
    return [dict(zip(columns, row, strict=True)) for row in q_all(conn, sql)]


def field_state(name: str, states: dict[str, str]) -> str:
    return states.get(name, "")


def render_records(
    title: str,
    color: str,
    records: list[dict[str, object]],
    fields: list[tuple[str, str]],
    states: dict[str, str],
    duplicate_badge: bool,
) -> None:
    body = [
        label(title),
        f'<div style="height:3px;background:{color};margin:0.3rem 0 0.6rem;"></div>',
    ]
    if not records:
        body.append(
            f'<div style="color:{ACCENT_RED};text-align:center;padding:1.5rem 0;font-weight:600;">NO RECORD</div>'
        )
    for index, record in enumerate(records):
        if duplicate_badge and index > 0:
            body.append(pill("DUPLICATE", ACCENT_AMBER))
        for key, caption in fields:
            state = field_state(key, states)
            border = ""
            value_color = TEXT_PRIMARY
            if state == "ok":
                border = f"border-left:2px solid {ACCENT_GREEN};padding-left:6px;"
            elif state == "bad":
                border = f"border-left:2px solid {ACCENT_RED};padding-left:6px;"
                value_color = ACCENT_RED
            raw = record.get(key)
            if key == "amount_inr" and raw is not None:
                shown = fmt_inr(float(raw))
            else:
                shown = "—" if raw is None else str(raw)
            body.append(
                f'<div style="margin-bottom:0.45rem;">{label(caption)}'
                f'<div style="{border}color:{value_color};font-family:{MONO};font-size:0.8125rem;">'
                f"{esc(shown)}</div></div>"
            )
    st.markdown(
        f'<div style="background:{SURFACE};border:1px solid {BORDER};padding:0.75rem 0.9rem;height:100%;">'
        f"{''.join(body)}</div>",
        unsafe_allow_html=True,
    )


def comparison_states(
    npci: list[dict[str, object]],
    ledger: list[dict[str, object]],
    merchant: list[dict[str, object]],
) -> dict[str, str]:
    states: dict[str, str] = {}
    present = [rows for rows in (npci, ledger, merchant) if rows]
    if len(present) >= 2:
        states["npci_ref"] = "ok"
    amounts = []
    for rows in present:
        if rows[0].get("amount_inr") is not None:
            amounts.append(round(float(rows[0]["amount_inr"]), 2))
    if len(amounts) >= 2:
        states["amount_inr"] = "ok" if len(set(amounts)) == 1 else "bad"
    times = [as_dt(rows[0].get("txn_ts")) for rows in present]
    times = [item for item in times if item is not None]
    if len(times) >= 2:
        delta = (max(times) - min(times)).total_seconds()
        states["txn_ts"] = "bad" if delta > 300 else "ok"
    if npci and ledger:
        nstat = str(npci[0].get("status") or "")
        lstat = str(ledger[0].get("status") or "")
        ldir = str(ledger[0].get("direction") or "")
        bad = (nstat == "FAILED" and lstat == "POSTED") or (
            nstat == "REVERSED" and ldir == "CREDIT" and lstat == "POSTED"
        )
        states["status"] = "bad" if bad else "ok"
    return states


def render_timeline(
    npci: list[dict[str, object]],
    ledger: list[dict[str, object]],
    merchant: list[dict[str, object]],
    breaks: list[dict[str, object]],
) -> None:
    events: list[tuple[datetime, str, str, str]] = []
    for row in npci:
        when = as_dt(row.get("txn_ts"))
        if when:
            events.append(
                (
                    when,
                    "NPCI",
                    ACCENT_BLUE,
                    f"Settlement filed — {row.get('status')} — {fmt_inr(float(row['amount_inr']))}",
                )
            )
    for row in ledger:
        when = as_dt(row.get("posting_ts")) or as_dt(row.get("txn_ts"))
        if when:
            events.append(
                (
                    when,
                    "BANK",
                    ACCENT_GREEN,
                    (
                        f"Ledger posted — {row.get('direction')} {row.get('status')} — "
                        f"{fmt_inr(float(row['amount_inr']))}"
                    ),
                )
            )
    for row in merchant:
        when = as_dt(row.get("txn_ts"))
        if when:
            events.append(
                (
                    when,
                    "MERCHANT",
                    ACCENT_AMBER,
                    f"Transaction recorded — {row.get('status')} — {fmt_inr(float(row['amount_inr']))}",
                )
            )
    events.sort(key=lambda item: item[0])
    if breaks and events:
        last = events[-1][0]
        for brk in breaks:
            events.append((last, "BREAK", ACCENT_RED, f"Break detected: {brk.get('break_type')}"))
    if not events:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};">No timeline events for this reference.</div>',
            unsafe_allow_html=True,
        )
        return
    rows = []
    for when, source, color, text in events:
        rows.append(
            f'<div style="margin:0 0 0.7rem 0.2rem;">'
            f'<span style="font-family:{MONO};color:{TEXT_MUTED};font-size:0.8125rem;">'
            f"{esc(when.strftime('%Y-%m-%d %H:%M:%S'))}</span> "
            f'<span style="color:{color};font-size:0.75rem;letter-spacing:0.05em;">'
            f"{esc(source)}</span> "
            f'<span style="color:{TEXT_PRIMARY};">{esc(text)}</span></div>'
        )
    st.markdown(
        f'<div style="border-left:2px solid {BORDER};padding-left:0.8rem;">{"".join(rows)}</div>',
        unsafe_allow_html=True,
    )


def decide(conn: pyexasol.ExaConnection, proposal_id: str, decision: str) -> None:
    pid = sql_text(proposal_id)
    current = q_val(conn, f"SELECT status FROM proposals WHERE proposal_id = '{pid}'")
    if current != "PENDING":
        return
    action = "APPROVE" if decision == "APPROVED" else "REJECT"
    did = f"D-{secrets.token_hex(4)}"
    conn.execute(
        "INSERT INTO decisions "
        "(decision_id, proposal_id, decided_by, decision_name, decided_at, note) "
        f"VALUES ('{did}', '{pid}', 'investigator', '{decision}', NOW(), "
        "'Decided in CloseDesk UI')"
    )
    conn.execute(f"UPDATE proposals SET status = '{decision}' WHERE proposal_id = '{pid}'")
    conn.execute(
        "INSERT INTO audit_log "
        "(at_ts, actor, action_name, entity_type, entity_id, before_json, after_json) "
        f"VALUES (NOW(), 'investigator', '{action}', 'proposal', '{pid}', 'PENDING', '{decision}')"
    )


def screen_investigate(conn: pyexasol.ExaConnection) -> None:
    if not st.session_state.run_id:
        empty_run("Run the pipeline first")
        return
    heading("Transaction investigator", "1.5rem")
    run_id = sql_text(str(st.session_state.run_id))
    try:
        picks = q_all(
            conn,
            "SELECT npci_ref, break_type, amount_inr FROM breaks "
            f"WHERE run_id = '{run_id}' AND npci_ref IS NOT NULL "
            "ORDER BY rupees_at_risk DESC LIMIT 6",
        )
    except pyexasol.ExaQueryError as exc:
        show_query_error(exc)
        picks = []
    search_col, button_col = st.columns([7, 3])
    with search_col:
        st.text_input(
            "NPCI reference",
            key="inv_search",
            placeholder="Enter NPCI reference (e.g., NPCI202610270012345)",
            label_visibility="collapsed",
        )
    with button_col:
        st.button("Search", type="primary", width="stretch")
    if picks:
        st.markdown(label("Highest ₹ at risk"), unsafe_allow_html=True)
        pick_cols = st.columns(len(picks))
        for col, pick in zip(pick_cols, picks, strict=True):
            ref, break_type, amount = pick
            caption = f"{ref} · {break_type} · {fmt_inr(float(amount))}"
            col.button(
                caption,
                key=widget_id("pick", str(ref) + str(break_type)),
                on_click=lambda chosen=str(ref): st.session_state.update(inv_search=chosen),
                width="stretch",
            )
    raw_ref = str(st.session_state.get("inv_search") or "")
    if not raw_ref.strip():
        return
    ref = safe_ref(raw_ref)
    if ref is None:
        st.markdown(
            f'<div style="color:{ACCENT_RED};">Reference must be letters and digits only.</div>',
            unsafe_allow_html=True,
        )
        return
    npci_cols = [
        "npci_ref",
        "txn_ts",
        "amount_inr",
        "status",
        "payer_psp",
        "payee_psp",
        "merchant_id",
        "mcc",
        "gateway_id",
    ]
    ledger_cols = [
        "ledger_id",
        "npci_ref",
        "txn_ts",
        "amount_inr",
        "direction",
        "account_id",
        "status",
        "posting_ts",
    ]
    merchant_cols = [
        "merchant_txn_id",
        "npci_ref",
        "txn_ts",
        "amount_inr",
        "merchant_id",
        "gateway_id",
        "status",
    ]
    try:
        npci = fetch_dicts(
            conn,
            f"SELECT {', '.join(npci_cols)} FROM npci_settlement WHERE npci_ref = '{ref}'",
            npci_cols,
        )
        ledger = fetch_dicts(
            conn,
            f"SELECT {', '.join(ledger_cols)} FROM bank_ledger WHERE npci_ref = '{ref}' ORDER BY ledger_id",
            ledger_cols,
        )
        merchant = fetch_dicts(
            conn,
            "SELECT "
            + ", ".join(merchant_cols)
            + f" FROM merchant_records WHERE npci_ref = '{ref}' ORDER BY merchant_txn_id",
            merchant_cols,
        )
        match_rows = q_all(
            conn,
            "SELECT stage, amount_inr FROM matches "
            f"WHERE run_id = '{run_id}' AND npci_ref = '{ref}'",
        )
        break_cols = ["break_id", "break_type", "rupees_at_risk", "root_cause_id", "amount_inr"]
        break_rows = fetch_dicts(
            conn,
            "SELECT break_id, break_type, rupees_at_risk, root_cause_id, amount_inr FROM breaks "
            f"WHERE run_id = '{run_id}' AND npci_ref = '{ref}' ORDER BY rupees_at_risk DESC",
            break_cols,
        )
    except pyexasol.ExaQueryError as exc:
        show_query_error(exc)
        return
    states = comparison_states(npci, ledger, merchant)
    c1, c2, c3 = st.columns(3)
    with c1:
        render_records(
            "NPCI settlement",
            ACCENT_BLUE,
            npci,
            [
                ("npci_ref", "NPCI ref"),
                ("txn_ts", "Timestamp"),
                ("amount_inr", "Amount"),
                ("status", "Status"),
                ("payer_psp", "Payer PSP"),
                ("payee_psp", "Payee PSP"),
                ("merchant_id", "Merchant ID"),
                ("mcc", "MCC"),
                ("gateway_id", "Gateway"),
            ],
            states,
            False,
        )
    with c2:
        render_records(
            "Bank ledger",
            ACCENT_GREEN,
            ledger,
            [
                ("ledger_id", "Ledger ID"),
                ("npci_ref", "NPCI ref"),
                ("txn_ts", "Timestamp"),
                ("amount_inr", "Amount"),
                ("direction", "Direction"),
                ("account_id", "Account"),
                ("status", "Status"),
                ("posting_ts", "Posting time"),
            ],
            states,
            True,
        )
    with c3:
        render_records(
            "Merchant records",
            ACCENT_AMBER,
            merchant,
            [
                ("merchant_txn_id", "Merchant txn"),
                ("npci_ref", "NPCI ref"),
                ("txn_ts", "Timestamp"),
                ("amount_inr", "Amount"),
                ("merchant_id", "Merchant ID"),
                ("gateway_id", "Gateway"),
                ("status", "Status"),
            ],
            states,
            False,
        )
    left, right = st.columns(2)
    with left:
        st.markdown(label("Timeline"), unsafe_allow_html=True)
        render_timeline(npci, ledger, merchant, break_rows)
    with right:
        st.markdown(label("Analysis"), unsafe_allow_html=True)
        if match_rows:
            stages = ", ".join(str(row[0]) for row in match_rows)
            st.markdown(
                f'<div style="color:{ACCENT_GREEN};font-size:1.125rem;font-weight:600;">✓ RECONCILED</div>'
                f'<div style="color:{TEXT_SECONDARY};font-family:{MONO};">{esc(stages)}</div>',
                unsafe_allow_html=True,
            )
        if not break_rows and not match_rows:
            st.markdown(
                f'<div style="color:{TEXT_MUTED};">This reference is not in the current run.</div>',
                unsafe_allow_html=True,
            )
        for brk in break_rows:
            title = ""
            if brk.get("root_cause_id"):
                try:
                    title = str(
                        q_val(
                            conn,
                            "SELECT title FROM root_causes "
                            f"WHERE run_id = '{run_id}' AND root_cause_id = '{sql_text(str(brk['root_cause_id']))}'",
                        )
                        or ""
                    )
                except pyexasol.ExaQueryError:
                    title = ""
            proposals = q_all(
                conn,
                "SELECT proposal_id, action_name, explanation, gate_decision, status "
                "FROM proposals "
                f"WHERE run_id = '{run_id}' AND break_id = {int(brk['break_id'])}",
            )
            gate_name = str(proposals[0][3]) if proposals else ""
            gate_icon = {"allow": "🟢", "escalate": "🟡", "block": "🔴"}.get(gate_name, "")
            st.markdown(
                f"""
                <div style="margin-top:0.8rem;">
                  {pill(str(brk["break_type"]), ACCENT_RED)}
                  <div style="font-family:{MONO};font-size:1.5rem;font-weight:600;color:{RUPEE_RED};">
                    {esc(fmt_inr(float(brk["rupees_at_risk"])))}
                  </div>
                  <div style="color:{TEXT_SECONDARY};">{esc(title)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if proposals:
                pid, action, explanation, _gate, status = proposals[0]
                st.markdown(
                    f'<div style="margin:0.4rem 0;color:{TEXT_PRIMARY};">{esc(action)} '
                    f"{gate_icon} {esc(str(_gate))}</div>"
                    f'<div style="color:{TEXT_SECONDARY};font-size:0.8125rem;">{esc(explanation)}</div>'
                    f'<div style="color:{TEXT_MUTED};font-size:0.75rem;margin-top:0.25rem;">'
                    f"STATUS {esc(status)}</div>",
                    unsafe_allow_html=True,
                )
                if status == "PENDING":
                    a_col, r_col = st.columns(2)
                    if a_col.button("Approve", key=widget_id("ok_inv", str(pid))):
                        decide(conn, str(pid), "APPROVED")
                        st.rerun()
                    if r_col.button("Reject", key=widget_id("no_inv", str(pid))):
                        decide(conn, str(pid), "REJECTED")
                        st.rerun()


# --- Injection ----------------------------------------------------------------


def make_plan(break_type: str, amount: float, gateway: str) -> dict[str, object]:
    ref = f"INJ{datetime.now().strftime('%H%M%S')}{secrets.token_hex(2).upper()}"
    txn_ts = "2026-10-27 15:04:05.000"
    post_ts = "2026-10-27 15:04:06.000"
    delta = secrets.randbelow(49) + 2
    merchant_amount = round(amount + delta, 2) if break_type == "amount_mismatch" else amount
    ledger_id = f"IL{ref[-12:]}"
    ledger_dup = f"ILD{ref[-11:]}"
    merchant_id = "M100001"
    merchant_txn = f"MR{ref[-12:]}"
    account = "A10000001"
    rows: list[tuple[str, list[str], list[object]]] = []
    npci_status = "SUCCESS"
    direction = "CREDIT"
    ledger_status = "POSTED"
    if break_type == "failed_but_debited":
        npci_status = "FAILED"
        direction = "DEBIT"
    elif break_type == "reversal_not_posted":
        npci_status = "REVERSED"
    if break_type != "missing_settlement":
        rows.append(
            (
                "npci_settlement",
                [
                    "npci_ref",
                    "txn_ts",
                    "amount_inr",
                    "status",
                    "payer_psp",
                    "payee_psp",
                    "merchant_id",
                    "mcc",
                    "gateway_id",
                ],
                [ref, txn_ts, amount, npci_status, "SBI", "HDFC", merchant_id, "5411", gateway],
            )
        )
    rows.append(
        (
            "bank_ledger",
            [
                "ledger_id",
                "npci_ref",
                "txn_ts",
                "amount_inr",
                "direction",
                "account_id",
                "status",
                "posting_ts",
            ],
            [ledger_id, ref, txn_ts, amount, direction, account, ledger_status, post_ts],
        )
    )
    if break_type == "duplicate_ledger":
        rows.append(
            (
                "bank_ledger",
                [
                    "ledger_id",
                    "npci_ref",
                    "txn_ts",
                    "amount_inr",
                    "direction",
                    "account_id",
                    "status",
                    "posting_ts",
                ],
                [ledger_dup, ref, txn_ts, amount, direction, account, ledger_status, post_ts],
            )
        )
    if break_type not in ("failed_but_debited", "reversal_not_posted"):
        rows.append(
            (
                "merchant_records",
                [
                    "merchant_txn_id",
                    "npci_ref",
                    "txn_ts",
                    "amount_inr",
                    "merchant_id",
                    "gateway_id",
                    "status",
                ],
                [merchant_txn, ref, txn_ts, merchant_amount, merchant_id, gateway, "SUCCESS"],
            )
        )
    return {
        "ref": ref,
        "break_type": break_type,
        "amount": amount,
        "merchant_amount": merchant_amount,
        "gateway": gateway,
        "ledger_id": ledger_id,
        "ledger_dup": ledger_dup if break_type == "duplicate_ledger" else None,
        "merchant_txn": merchant_txn,
        "rows": rows,
    }


def preview_html(plan: dict[str, object]) -> str:
    lines = []
    for table, _cols, vals in plan["rows"]:  # type: ignore[union-attr]
        shown = " · ".join(str(v) for v in vals[:4])
        lines.append(
            f'<tr style="border-bottom:1px solid {BORDER};">'
            f'<td style="padding:0.3rem 0.4rem;color:{TEXT_SECONDARY};">{esc(table)}</td>'
            f'<td style="padding:0.3rem 0.4rem;font-family:{MONO};color:{TEXT_PRIMARY};">{esc(shown)}</td>'
            f"</tr>"
        )
    return (
        f'<div style="background:{SURFACE_ELEVATED};border:1px solid {BORDER};padding:0.6rem;margin-top:0.6rem;">'
        f"{label('Rows that will be inserted')}"
        f'<table style="width:100%;border-collapse:collapse;font-size:0.8125rem;">{"".join(lines)}</table>'
        f"</div>"
    )


def insert_plan(conn: pyexasol.ExaConnection, plan: dict[str, object]) -> None:
    for table, cols, vals in plan["rows"]:  # type: ignore[union-attr]
        col_sql = ", ".join(cols)
        val_sql = ", ".join(sql_literal(v) for v in vals)
        conn.execute(f"INSERT INTO {table} ({col_sql}) VALUES ({val_sql})")


def detect_break(conn: pyexasol.ExaConnection, run_id: str, plan: dict[str, object]) -> int | None:
    ref = str(plan["ref"])
    break_type = str(plan["break_type"])
    amount = float(plan["amount"])
    rid = sql_text(run_id)
    safe = sql_text(ref)
    if break_type == "duplicate_ledger":
        row = conn.execute(
            "SELECT dup.ledger_id, dup.amount_inr FROM bank_ledger dup "
            "JOIN (SELECT npci_ref, MIN(ledger_id) AS keep_id FROM bank_ledger "
            f"WHERE npci_ref = '{safe}' GROUP BY npci_ref HAVING COUNT(*) > 1) g "
            "ON g.npci_ref = dup.npci_ref AND dup.ledger_id <> g.keep_id"
        ).fetchone()
        if not row:
            return None
        ledger_id, amt = row[0], float(row[1])
        merchant = None
    elif break_type == "amount_mismatch":
        row = conn.execute(
            "SELECT MIN(l.ledger_id), MIN(m.merchant_txn_id), MIN(n.amount_inr) "
            "FROM npci_settlement n "
            "LEFT JOIN bank_ledger l ON l.npci_ref = n.npci_ref "
            "LEFT JOIN merchant_records m ON m.npci_ref = n.npci_ref "
            f"WHERE n.npci_ref = '{safe}' "
            "GROUP BY n.npci_ref "
            "HAVING MIN(m.amount_inr) <> MIN(n.amount_inr)"
        ).fetchone()
        if not row:
            return None
        ledger_id, merchant, amt = row[0], row[1], float(row[2])
    elif break_type == "failed_but_debited":
        row = conn.execute(
            "SELECT l.ledger_id, l.amount_inr FROM bank_ledger l "
            f"WHERE l.npci_ref = '{safe}' AND l.direction = 'DEBIT' AND l.status = 'POSTED' "
            "AND NOT EXISTS (SELECT 1 FROM npci_settlement n "
            f"WHERE n.npci_ref = l.npci_ref AND n.status = 'SUCCESS')"
        ).fetchone()
        if not row:
            return None
        ledger_id, amt = row[0], float(row[1])
        merchant = None
    elif break_type == "missing_settlement":
        row = conn.execute(
            "SELECT l.ledger_id, l.amount_inr, MIN(m.merchant_txn_id) "
            "FROM bank_ledger l "
            "LEFT JOIN npci_settlement n ON n.npci_ref = l.npci_ref "
            "LEFT JOIN merchant_records m ON m.npci_ref = l.npci_ref "
            f"WHERE l.npci_ref = '{safe}' AND n.npci_ref IS NULL "
            "GROUP BY l.ledger_id, l.amount_inr"
        ).fetchone()
        if not row:
            return None
        ledger_id, amt, merchant = row[0], float(row[1]), row[2]
    else:
        row = conn.execute(
            "SELECT l.ledger_id, n.amount_inr FROM npci_settlement n "
            "JOIN bank_ledger l ON l.npci_ref = n.npci_ref "
            f"WHERE n.npci_ref = '{safe}' AND n.status = 'REVERSED' "
            "AND l.direction = 'CREDIT' AND l.status = 'POSTED'"
        ).fetchone()
        if not row:
            return None
        ledger_id, amt = row[0], float(row[1])
        merchant = None
    conn.execute(
        "INSERT INTO breaks "
        "(run_id, npci_ref, ledger_id, merchant_txn_id, break_type, amount_inr, rupees_at_risk, deadline_ts) "
        f"VALUES ('{rid}', '{safe}', {sql_literal(ledger_id)}, {sql_literal(merchant)}, "
        f"'{break_type}', {amt}, {amt}, NULL)"
    )
    bid = q_val(
        conn,
        "SELECT MAX(break_id) FROM breaks "
        f"WHERE run_id = '{rid}' AND npci_ref = '{safe}' AND break_type = '{break_type}'",
    )
    _ = amount
    return int(bid) if bid is not None else None


def propose_one(
    conn: pyexasol.ExaConnection, run_id: str, break_id: int, plan: dict[str, object]
) -> str:
    break_type = str(plan["break_type"])
    action, template = ACTION_MAP[break_type]
    explanation = template.format(
        npci_ref=plan["ref"], amount=float(plan["amount"]), gateway=plan["gateway"]
    )
    decision = gate(action, float(plan["amount"]), load_policy(ROOT / "config" / "policy.yaml"))
    pid = f"P-{secrets.token_hex(4)}"
    gateway = str(plan["gateway"])
    rc_id = hashlib.md5(f"{gateway}|{break_type}".encode()).hexdigest()
    conn.execute(
        f"UPDATE breaks SET root_cause_id = '{rc_id}' "
        f"WHERE run_id = '{sql_text(run_id)}' AND break_id = {break_id}"
    )
    title = f"Gateway {gateway} · {break_type}"
    found = int(
        q_val(
            conn,
            "SELECT COUNT(*) FROM root_causes "
            f"WHERE run_id = '{sql_text(run_id)}' AND root_cause_id = '{rc_id}'",
        )
        or 0
    )
    if found:
        conn.execute(
            "UPDATE root_causes SET break_count = break_count + 1, "
            f"rupees_at_risk = rupees_at_risk + {float(plan['amount'])} "
            f"WHERE run_id = '{sql_text(run_id)}' AND root_cause_id = '{rc_id}'"
        )
    else:
        conn.execute(
            "INSERT INTO root_causes (run_id, root_cause_id, title, break_count, rupees_at_risk) "
            f"VALUES ('{sql_text(run_id)}', '{rc_id}', '{sql_text(title, 200)}', 1, {float(plan['amount'])})"
        )
    conn.execute(
        "INSERT INTO proposals "
        "(proposal_id, run_id, break_id, action_name, explanation, amount_inr, gate_decision, status, created_at) "
        f"VALUES ('{pid}', '{sql_text(run_id)}', {break_id}, '{action}', "
        f"'{sql_text(explanation)}', {float(plan['amount'])}, '{decision}', 'PENDING', NOW())"
    )
    conn.execute(
        "INSERT INTO audit_log (at_ts, actor, action_name, entity_type, entity_id, before_json, after_json) "
        f"VALUES (NOW(), 'closedesk-agent', 'PROPOSE', 'proposal', '{pid}', NULL, '{sql_text(explanation)}')"
    )
    return pid


def render_injection_result(result: dict[str, object]) -> str:
    steps = []
    steps.append(f'<div style="color:{ACCENT_GREEN};">✓ Inserted</div>')
    steps.append(
        f'<div style="font-family:{MONO};color:{TEXT_SECONDARY};font-size:0.8125rem;">'
        f"{esc(result.get('ref'))}</div>"
    )
    if result.get("detected"):
        steps.append(f'<div style="color:{ACCENT_GREEN};margin-top:0.6rem;">✓ Detected</div>')
        steps.append(
            f'<div style="font-family:{MONO};color:{TEXT_PRIMARY};">'
            f"{esc(result.get('break_type'))} · {esc(fmt_inr(float(result['amount'])))}</div>"
        )
    else:
        steps.append(f'<div style="color:{ACCENT_RED};margin-top:0.6rem;">✗ Missed</div>')
    if result.get("proposal_id"):
        gate_name = str(result.get("gate") or "")
        icon = {"allow": "🟢", "escalate": "🟡", "block": "🔴"}.get(gate_name, "")
        steps.append(f'<div style="color:{ACCENT_GREEN};margin-top:0.6rem;">✓ Proposed</div>')
        steps.append(
            f'<div style="color:{TEXT_PRIMARY};">{esc(result.get("action"))} {icon} {esc(gate_name)}</div>'
            f'<div style="color:{TEXT_SECONDARY};font-size:0.8125rem;">{esc(result.get("explanation"))}</div>'
        )
    return f'<div style="background:{SURFACE};border:1px solid {BORDER};padding:1rem;">{"".join(steps)}</div>'


def run_injection(conn: pyexasol.ExaConnection, plan: dict[str, object], box: object) -> None:
    run_id = str(st.session_state.run_id)
    box.markdown(
        f'<div style="color:{ACCENT_BLUE};font-family:{MONO};">Inserting transaction...</div>',
        unsafe_allow_html=True,
    )
    insert_plan(conn, plan)
    time.sleep(0.3)
    box.markdown(
        f'<div style="color:{ACCENT_GREEN};">✓ Inserted</div>'
        f'<div style="font-family:{MONO};color:{TEXT_SECONDARY};">{esc(plan["ref"])}</div>'
        f'<div style="color:{ACCENT_BLUE};font-family:{MONO};margin-top:0.6rem;">Running detection...</div>',
        unsafe_allow_html=True,
    )
    break_id = detect_break(conn, run_id, plan)
    time.sleep(0.3)
    proposal_id = None
    action = explanation = decision = ""
    if break_id is not None:
        box.markdown(
            f'<div style="color:{ACCENT_GREEN};">✓ Detected</div>'
            f'<div style="color:{ACCENT_BLUE};font-family:{MONO};margin-top:0.6rem;">Generating proposal...</div>',
            unsafe_allow_html=True,
        )
        proposal_id = propose_one(conn, run_id, break_id, plan)
        row = conn.execute(
            "SELECT action_name, explanation, gate_decision FROM proposals "
            f"WHERE proposal_id = '{proposal_id}'"
        ).fetchone()
        action, explanation, decision = str(row[0]), str(row[1]), str(row[2])
        time.sleep(0.3)
    result = {
        "ref": plan["ref"],
        "break_type": plan["break_type"],
        "amount": plan["amount"],
        "detected": break_id is not None,
        "break_id": break_id,
        "proposal_id": proposal_id,
        "action": action,
        "explanation": explanation,
        "gate": decision,
    }
    st.session_state.injection_result = result
    st.session_state.injected_breaks.append(result)
    st.session_state.inj_sig = None
    box.markdown(render_injection_result(result), unsafe_allow_html=True)


def screen_inject(conn: pyexasol.ExaConnection) -> None:
    if not st.session_state.run_id:
        empty_run("Run the pipeline first")
        return
    left, right = st.columns([9, 11])
    with left:
        heading("Inject a break")
        st.markdown(
            f'<div style="color:{TEXT_SECONDARY};margin-bottom:0.8rem;">'
            "Add a problematic transaction to the live dataset and watch CloseDesk detect it."
            "</div>",
            unsafe_allow_html=True,
        )
        labels = [item[0] for item in INJECT_TYPES]
        chosen = st.selectbox("Break type", labels)
        break_type = dict(INJECT_TYPES)[chosen]
        amount = float(
            st.number_input("Amount (₹)", min_value=100, max_value=500000, value=25000, step=1000)
        )
        try:
            gateways = [
                str(row[0])
                for row in q_all(
                    conn,
                    "SELECT DISTINCT gateway_id FROM npci_settlement WHERE gateway_id IS NOT NULL LIMIT 10",
                )
            ]
        except pyexasol.ExaQueryError:
            gateways = []
        gateway = st.selectbox("Gateway", gateways or GATEWAYS)
        sig = (break_type, amount, str(gateway))
        if st.session_state.inj_sig != sig or not st.session_state.inj_plan:
            st.session_state.inj_plan = make_plan(break_type, amount, str(gateway))
            st.session_state.inj_sig = sig
        st.markdown(preview_html(st.session_state.inj_plan), unsafe_allow_html=True)
        clicked = st.button("INJECT & DETECT", key="inject_btn", type="primary", width="stretch")
    with right:
        box = st.empty()
        if clicked and st.session_state.inj_plan:
            try:
                run_injection(conn, st.session_state.inj_plan, box)
            except pyexasol.ExaError as exc:
                show_query_error(exc)
        elif st.session_state.injection_result:
            box.markdown(
                render_injection_result(st.session_state.injection_result), unsafe_allow_html=True
            )
            result = st.session_state.injection_result
            if result.get("proposal_id") and result.get("detected"):
                pid = str(result["proposal_id"])
                status = q_val(
                    conn, f"SELECT status FROM proposals WHERE proposal_id = '{sql_text(pid)}'"
                )
                if status == "PENDING":
                    a_col, r_col = st.columns(2)
                    if a_col.button("Approve", key=widget_id("ok_inj", pid)):
                        decide(conn, pid, "APPROVED")
                        st.rerun()
                    if r_col.button("Reject", key=widget_id("no_inj", pid)):
                        decide(conn, pid, "REJECTED")
                        st.rerun()
        else:
            box.markdown(
                f'<div style="color:{TEXT_MUTED};padding:2rem 0;">'
                "Inject a break to see detection results here.</div>",
                unsafe_allow_html=True,
            )


# --- Exceptions ---------------------------------------------------------------


def screen_exceptions(conn: pyexasol.ExaConnection) -> None:
    if not st.session_state.run_id:
        empty_run("Run the pipeline first")
        return
    run_id = sql_text(str(st.session_state.run_id))
    try:
        summary = q_all(
            conn,
            "SELECT status, COUNT(*), COALESCE(SUM(amount_inr), 0) FROM proposals "
            f"WHERE run_id = '{run_id}' GROUP BY status",
        )
        types = [
            str(row[0])
            for row in q_all(
                conn,
                f"SELECT DISTINCT break_type FROM breaks WHERE run_id = '{run_id}' ORDER BY 1",
            )
        ]
    except pyexasol.ExaQueryError as exc:
        show_query_error(exc)
        return
    counts = {str(row[0]): (int(row[1]), float(row[2])) for row in summary}
    pending = counts.get("PENDING", (0, 0.0))[0]
    approved = counts.get("APPROVED", (0, 0.0))[0]
    rejected = counts.get("REJECTED", (0, 0.0))[0]
    risk = sum(pair[1] for pair in counts.values())
    st.markdown(
        f"""
        <div style="display:flex;background:{SURFACE};border:1px solid {BORDER};">
          <div style="flex:1;padding:0.7rem 1rem;border-right:1px solid {BORDER};color:{ACCENT_AMBER};">
            PENDING: {pending:,}</div>
          <div style="flex:1;padding:0.7rem 1rem;border-right:1px solid {BORDER};color:{ACCENT_GREEN};">
            APPROVED: {approved:,}</div>
          <div style="flex:1;padding:0.7rem 1rem;border-right:1px solid {BORDER};color:{ACCENT_RED};">
            REJECTED: {rejected:,}</div>
          <div style="flex:1.4;padding:0.7rem 1rem;color:{RUPEE_RED};font-size:1.125rem;font-weight:600;">
            TOTAL ₹ AT RISK: {esc(fmt_inr_short(risk))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    f1, f2, f3 = st.columns(3)
    break_choice = f1.selectbox("Break type", ["All", *types])
    gate_choice = f2.selectbox("Gate", ["All", "Allow", "Escalate", "Block"])
    status_choice = f3.selectbox("Status", ["All", "Pending", "Approved", "Rejected"])
    sig = (break_choice, gate_choice, status_choice)
    if st.session_state.ex_sig != sig:
        st.session_state.ex_offset = 0
        st.session_state.ex_sig = sig
    filters = [f"p.run_id = '{run_id}'"]
    if break_choice != "All" and break_choice in types:
        filters.append(f"b.break_type = '{sql_text(break_choice)}'")
    gate_map = {"Allow": "allow", "Escalate": "escalate", "Block": "block"}
    if gate_choice in gate_map:
        filters.append(f"p.gate_decision = '{gate_map[gate_choice]}'")
    status_map = {"Pending": "PENDING", "Approved": "APPROVED", "Rejected": "REJECTED"}
    if status_choice in status_map:
        filters.append(f"p.status = '{status_map[status_choice]}'")
    where = " AND ".join(filters)
    try:
        total = int(
            q_val(
                conn,
                "SELECT COUNT(*) FROM proposals p "
                "JOIN breaks b ON b.run_id = p.run_id AND b.break_id = p.break_id "
                f"WHERE {where}",
            )
            or 0
        )
        offset = int(st.session_state.ex_offset)
        rows = q_all(
            conn,
            "SELECT p.proposal_id, p.action_name, p.explanation, p.amount_inr, p.gate_decision, "
            "p.status, b.npci_ref, b.break_type, b.rupees_at_risk, IFNULL(n.gateway_id, '-') "
            "FROM proposals p "
            "JOIN breaks b ON b.run_id = p.run_id AND b.break_id = p.break_id "
            "LEFT JOIN npci_settlement n ON n.npci_ref = b.npci_ref "
            f"WHERE {where} "
            "ORDER BY b.rupees_at_risk DESC, p.proposal_id "
            f"LIMIT 50 OFFSET {offset}",
        )
    except pyexasol.ExaQueryError as exc:
        show_query_error(exc)
        return
    if not rows:
        st.markdown(
            f'<div style="color:{TEXT_MUTED};margin-top:1rem;">No proposals match these filters.</div>',
            unsafe_allow_html=True,
        )
    gate_color = {"allow": ACCENT_GREEN, "escalate": ACCENT_AMBER, "block": ACCENT_RED}
    status_color = {"PENDING": ACCENT_AMBER, "APPROVED": ACCENT_GREEN, "REJECTED": ACCENT_RED}
    for row in rows:
        pid, action, explanation, _amount, gate_name, status, ref, break_type, risk, gateway = row
        bar = gate_color.get(str(gate_name), BORDER)
        c0, c1, c2, c3, c4, c5 = st.columns([0.12, 1.1, 2.4, 1.8, 3.2, 1.6])
        c0.markdown(
            f'<div style="width:4px;height:64px;background:{bar};"></div>',
            unsafe_allow_html=True,
        )
        c1.markdown(
            pill(str(gate_name).upper(), gate_color.get(str(gate_name), TEXT_SECONDARY))
            + "<br>"
            + pill(str(status), status_color.get(str(status), TEXT_SECONDARY)),
            unsafe_allow_html=True,
        )
        c2.markdown(
            f'<div style="font-family:{MONO};font-size:0.8125rem;color:{TEXT_PRIMARY};">{esc(ref)}</div>'
            f'<div style="color:{TEXT_SECONDARY};font-size:0.75rem;">{esc(break_type)}</div>'
            f'<div style="color:{TEXT_MUTED};font-size:0.75rem;">{esc(gateway)}</div>',
            unsafe_allow_html=True,
        )
        c3.markdown(
            f"{label('₹ at risk')}"
            f'<div style="font-family:{MONO};font-size:1.125rem;font-weight:600;color:{TEXT_PRIMARY};">'
            f"{esc(fmt_inr(float(risk)))}</div>",
            unsafe_allow_html=True,
        )
        c4.markdown(
            f'<div style="color:{TEXT_SECONDARY};font-size:0.8125rem;">{esc(str(explanation)[:120])}</div>'
            f'<div style="color:{TEXT_MUTED};font-size:0.75rem;margin-top:0.2rem;">{esc(action)}</div>',
            unsafe_allow_html=True,
        )
        if status == "PENDING":
            if c5.button("Approve", key=widget_id("ok", str(pid))):
                decide(conn, str(pid), "APPROVED")
                st.rerun()
            if c5.button("Reject", key=widget_id("no", str(pid))):
                decide(conn, str(pid), "REJECTED")
                st.rerun()
    shown_end = min(offset + len(rows), total)
    shown_start = 0 if total == 0 else offset + 1
    st.markdown(
        f'<div style="color:{TEXT_SECONDARY};margin-top:0.5rem;">'
        f"Showing {shown_start:,}–{shown_end:,} of {total:,}</div>",
        unsafe_allow_html=True,
    )
    prev, _mid, nxt = st.columns([1, 3, 1])
    if prev.button("Previous", disabled=offset <= 0):
        st.session_state.ex_offset = max(0, offset - 50)
        st.rerun()
    if nxt.button("Next", disabled=offset + 50 >= total):
        st.session_state.ex_offset = offset + 50
        st.rerun()


# --- Analytics ----------------------------------------------------------------


def funnel_html(npci: int, matched: int, breaks: int, causes: int) -> str:
    blocks = [
        (f"{npci:,}", "NPCI txns", ACCENT_BLUE),
        (f"{matched:,}", "Matched", ACCENT_GREEN),
        (f"{breaks:,}", "Breaks", ACCENT_RED),
        (f"{causes:,}", "Root causes", ACCENT_AMBER),
    ]
    parts = []
    for index, (count, caption, color) in enumerate(blocks):
        if index:
            parts.append(
                f'<div style="color:{BORDER_FOCUS};font-size:1.5rem;padding:0 0.3rem;">→</div>'
            )
        parts.append(
            f'<div style="flex:1;background:{color};padding:0.9rem 0.4rem;text-align:center;">'
            f'<div style="font-family:{MONO};font-size:1.35rem;font-weight:600;color:#ffffff;">{count}</div>'
            f'<div style="font-size:0.75rem;letter-spacing:0.05em;text-transform:uppercase;color:#ffffff;">'
            f"{esc(caption)}</div></div>"
        )
    return f'<div style="display:flex;align-items:center;width:100%;">{"".join(parts)}</div>'


def html_table(headers: list[str], records: list[list[str]], numeric_cols: set[int]) -> str:
    head = "".join(
        f'<th style="text-align:{"right" if i in numeric_cols else "left"};padding:0.45rem;'
        f"font-size:0.75rem;letter-spacing:0.05em;text-transform:uppercase;color:{TEXT_SECONDARY};"
        f'font-weight:500;border-bottom:1px solid {BORDER};">{esc(h)}</th>'
        for i, h in enumerate(headers)
    )
    body = []
    for idx, record in enumerate(records):
        bg = SURFACE_ELEVATED if idx % 2 else SURFACE
        cells = []
        for col, value in enumerate(record):
            align = "right" if col in numeric_cols else "left"
            family = MONO if col in numeric_cols else "inherit"
            cells.append(
                f'<td style="text-align:{align};padding:0.4rem 0.45rem;font-family:{family};">{esc(value)}</td>'
            )
        body.append(f'<tr style="background:{bg};color:{TEXT_PRIMARY};">{"".join(cells)}</tr>')
    return (
        f'<table style="width:100%;border-collapse:collapse;font-size:0.8125rem;">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def dark_bar(frame: pd.DataFrame, y_name: str, x_name: str, color: str | None) -> alt.Chart:
    y_enc = alt.Y(
        f"{y_name}:N", sort="-x", axis=alt.Axis(labelColor=TEXT_PRIMARY, title=None, grid=False)
    )
    x_enc = alt.X(
        f"{x_name}:Q",
        axis=alt.Axis(labelColor=TEXT_PRIMARY, title=None, gridColor=BORDER),
    )
    if color:
        color_enc = alt.Color(f"{y_name}:N", scale=alt.Scale(range=CHART_PALETTE), legend=None)
        chart = alt.Chart(frame).mark_bar().encode(y=y_enc, x=x_enc, color=color_enc)
    else:
        chart = alt.Chart(frame).mark_bar(color=ACCENT_CYAN).encode(y=y_enc, x=x_enc)
    return (
        chart.properties(height=280, background=SURFACE)
        .configure_view(strokeWidth=0)
        .configure(background=SURFACE)
        .configure_axis(domainColor=BORDER_FOCUS)
    )


def screen_analytics(conn: pyexasol.ExaConnection) -> None:
    if not st.session_state.run_id:
        empty_run("Run the pipeline first")
        return
    run_id = str(st.session_state.run_id)
    rid = sql_text(run_id)
    analytics, audit = st.tabs(["Analytics", "Audit Trail"])
    with analytics:
        try:
            stats = run_stats(conn, run_id)
            break_rows = q_all(
                conn,
                "SELECT break_type, COUNT(*) FROM breaks "
                f"WHERE run_id = '{rid}' GROUP BY break_type ORDER BY COUNT(*) DESC",
            )
            stage_rows = q_all(
                conn,
                "SELECT stage, elapsed_ms FROM match_stage_log "
                f"WHERE run_id = '{rid}' ORDER BY started_at",
            )
            causes = q_all(
                conn,
                "SELECT title, break_count, rupees_at_risk FROM root_causes "
                f"WHERE run_id = '{rid}' ORDER BY rupees_at_risk DESC",
            )
        except pyexasol.ExaQueryError as exc:
            show_query_error(exc)
            return
        st.markdown(
            funnel_html(
                int(stats["npci"]),
                int(stats["matched"]),
                int(stats["breaks"]),
                int(stats["causes"]),
            ),
            unsafe_allow_html=True,
        )
        left, right = st.columns(2)
        with left:
            st.markdown(label("Break type distribution"), unsafe_allow_html=True)
            if break_rows:
                frame = pd.DataFrame(
                    [(str(row[0]), int(row[1])) for row in break_rows],
                    columns=["break_type", "cnt"],
                )
                st.altair_chart(dark_bar(frame, "break_type", "cnt", "palette"), width="stretch")
            else:
                st.markdown(
                    f'<div style="color:{TEXT_MUTED};">No breaks in this run.</div>',
                    unsafe_allow_html=True,
                )
        with right:
            st.markdown(label("Stage performance"), unsafe_allow_html=True)
            if stage_rows:
                frame = pd.DataFrame(
                    [
                        (STAGE_LABELS.get(str(row[0]), str(row[0])), float(row[1]))
                        for row in stage_rows
                    ],
                    columns=["stage", "elapsed_ms"],
                )
                st.altair_chart(dark_bar(frame, "stage", "elapsed_ms", None), width="stretch")
        st.markdown(label("Root causes"), unsafe_allow_html=True)
        if causes:
            records = [[str(row[0]), f"{int(row[1]):,}", fmt_inr(float(row[2]))] for row in causes]
            st.markdown(
                html_table(["Title", "Break count", "₹ at risk"], records, {1, 2}),
                unsafe_allow_html=True,
            )
        has_key = int(q_val(conn, "SELECT COUNT(*) FROM answer_key") or 0) > 0
        if has_key and st.button("Score against answer key", key="score_run"):
            st.session_state.eval_result = score(run_id, env_path=ROOT / ".env")
        result = st.session_state.eval_result
        if result and result.get("run_id") == run_id:
            metrics = [
                ("Precision", result["precision"], ACCENT_GREEN),
                ("Recall", result["recall"], ACCENT_BLUE),
                ("F1", result["f1"], ACCENT_CYAN),
            ]
            cells = []
            for caption, value, color in metrics:
                cells.append(
                    f'<div style="flex:1;">{label(caption)}'
                    f'<div style="font-family:{MONO};font-size:2.25rem;font-weight:700;color:{color};">'
                    f"{float(value) * 100:.2f}%</div></div>"
                )
            st.markdown(
                f'<div style="display:flex;gap:1rem;margin-top:1rem;">{"".join(cells)}</div>',
                unsafe_allow_html=True,
            )
            type_rows = []
            for name, item in sorted(result["by_type"].items()):
                rate = item["tp"] / item["total"] if item["total"] else 0
                type_rows.append(
                    [name, f"{item['tp']:,}", f"{item['total']:,}", f"{rate * 100:.0f}%"]
                )
            st.markdown(
                html_table(["Break type", "Detected", "Planted", "Rate"], type_rows, {1, 2, 3}),
                unsafe_allow_html=True,
            )
    with audit:
        actor = st.selectbox("Actor", ["All", "closedesk-agent", "investigator"])
        action = st.selectbox("Action", ["All", "PROPOSE", "APPROVE", "REJECT"])
        filters = []
        if actor != "All":
            filters.append(f"actor = '{sql_text(actor)}'")
        if action != "All":
            filters.append(f"action_name = '{sql_text(action)}'")
        where = (" WHERE " + " AND ".join(filters)) if filters else ""
        try:
            audits = q_all(
                conn,
                "SELECT audit_id, at_ts, actor, action_name, entity_type, entity_id, "
                "before_json, after_json FROM audit_log "
                f"{where} ORDER BY audit_id DESC LIMIT 100",
            )
        except pyexasol.ExaQueryError as exc:
            show_query_error(exc)
            return
        if not audits:
            st.markdown(
                f'<div style="color:{TEXT_MUTED};">No audit entries yet.</div>',
                unsafe_allow_html=True,
            )
            return
        actor_color = {"closedesk-agent": ACCENT_BLUE, "investigator": ACCENT_GREEN}
        action_color = {"PROPOSE": ACCENT_BLUE, "APPROVE": ACCENT_GREEN, "REJECT": ACCENT_RED}
        for row in audits:
            _aid, at_ts, who, act, entity, entity_id, before, after = row
            before_s = "" if before is None else str(before)
            after_s = "" if after is None else str(after)
            change = f"{before_s[:80]} → {after_s[:80]}"
            title = esc(f"{before_s} → {after_s}")
            st.markdown(
                f'<div title="{title}" style="display:flex;gap:0.6rem;align-items:baseline;'
                f'border-bottom:1px solid {BORDER};padding:0.35rem 0;font-size:0.8125rem;">'
                f'<span style="font-family:{MONO};color:{TEXT_MUTED};min-width:11rem;">{esc(at_ts)}</span>'
                f"{pill('agent' if who == 'closedesk-agent' else str(who), actor_color.get(str(who), TEXT_SECONDARY))}"
                f"{pill(str(act), action_color.get(str(act), TEXT_SECONDARY))}"
                f'<span style="font-family:{MONO};color:{TEXT_PRIMARY};">{esc(entity)} {esc(entity_id)}</span>'
                f'<span style="color:{TEXT_SECONDARY};">{esc(change)}</span></div>',
                unsafe_allow_html=True,
            )


def main() -> None:
    os.chdir(ROOT)
    st.set_page_config(page_title="CloseDesk", layout="wide", initial_sidebar_state="expanded")
    init_state()
    inject_css()
    conn, error = acquire_connection()
    if conn is not None:
        bootstrap_run(conn)
    render_sidebar(conn, error)
    if conn is None:
        render_conn_error(error)
        return
    screen = st.session_state.screen
    try:
        if screen == "pipeline":
            screen_pipeline(conn)
        elif screen == "investigate":
            screen_investigate(conn)
        elif screen == "inject":
            screen_inject(conn)
        elif screen == "exceptions":
            screen_exceptions(conn)
        else:
            screen_analytics(conn)
    except pyexasol.ExaError as exc:
        show_query_error(exc)


if __name__ == "__main__":
    main()
