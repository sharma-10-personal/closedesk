"""Run SQL matching stages in order. Measure wall time per stage."""

from __future__ import annotations

import re
import secrets
import time
from pathlib import Path

import pyexasol
import yaml
from dotenv import dotenv_values

SQL_DIR = Path("sql")

STAGES = [
    ("10_match_exact.sql", "exact", "matches"),
    ("11_match_tolerance.sql", "tolerance", "matches"),
    ("12_match_many_to_one.sql", "many_to_one", "matches"),
    ("20_classify_breaks.sql", "classify", "breaks"),
    ("21_detect_orphans.sql", "orphans", "breaks"),
    ("22_detect_duplicates.sql", "duplicates", "breaks"),
    ("23_detect_status_mismatch.sql", "status_mismatch", "breaks"),
    ("30_root_causes.sql", "root_causes", "root_causes"),
    ("40_priority_and_deadlines.sql", "priority", "breaks"),
]


def _connect(env: dict[str, str | None]) -> pyexasol.ExaConnection:
    return pyexasol.connect(
        dsn=env.get("EXA_DSN", "localhost:8563"),
        user=env.get("EXA_USER", "sys"),
        password=env.get("EXA_PASSWORD", ""),
        schema=env.get("EXA_SCHEMA", "CLOSEDESK"),
        compression=True,
        websocket_sslopt={"cert_reqs": 0},
    )


def _sanitise_run_id(rid: str) -> str:
    """Only allow alphanumeric + hyphen."""
    return re.sub(r"[^A-Za-z0-9\-]", "", rid)


def _prepare_sql(
    raw: str,
    run_id: str,
    amount_tol: float,
    time_tol: int,
    rupees_per_day: float,
) -> list[str]:
    """Replace bindings and split into individual statements."""
    # Strip comment lines
    lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
    sql = "\n".join(lines)

    # Replace bindings (as string literals for :run_id, numbers for the rest)
    sql = sql.replace(":run_id", f"'{run_id}'")
    sql = sql.replace(":amount_tol", str(float(amount_tol)))
    sql = sql.replace(":time_tol_seconds", str(int(time_tol)))
    sql = sql.replace(":rupees_per_day", str(float(rupees_per_day)))

    # Split on semicolons, filter blanks
    stmts = [s.strip() for s in sql.split(";") if s.strip()]
    return stmts


def run_engine(
    env_path: Path | None = None,
    scenario_path: Path | None = None,
    policy_path: Path | None = None,
) -> str:
    """Execute all SQL stages and return run_id."""
    env = dotenv_values(env_path or Path(".env"))
    scenario = yaml.safe_load((scenario_path or Path("config/scenario.yaml")).read_text())
    policy = yaml.safe_load((policy_path or Path("config/policy.yaml")).read_text())

    iso_date = scenario["iso_date"]
    run_id = _sanitise_run_id(f"R-{iso_date}-{secrets.token_hex(3)}")

    amount_tol = scenario["tolerance"]["amount_inr"]
    time_tol = scenario["tolerance"]["time_seconds"]
    rupees_per_day = policy["compensation"]["rupees_per_day"]

    conn = _connect(env)
    schema = env.get("EXA_SCHEMA", "CLOSEDESK")
    conn.execute(f"OPEN SCHEMA {schema}")

    print(f"Run ID: {run_id}")
    print(f"{'Stage':<20} {'Rows':>12} {'₹ value':>18} {'Time':>10}")
    print("-" * 64)

    total_time = 0.0

    for sql_file, stage_name, result_table in STAGES:
        sql_path = SQL_DIR / sql_file
        if not sql_path.exists():
            print(f"SKIP {stage_name}: {sql_path} not found")
            continue

        raw = sql_path.read_text()
        stmts = _prepare_sql(raw, run_id, amount_tol, time_tol, rupees_per_day)

        t0 = time.perf_counter()
        for stmt in stmts:
            try:
                conn.execute(stmt)
            except pyexasol.ExaQueryError as e:
                print(f"\nSQL ERROR in {sql_file}:")
                print(f"  Statement: {stmt[:200]}")
                print(f"  Error: {e}")
                raise
        elapsed = time.perf_counter() - t0
        total_time += elapsed

        # Count rows and rupees for this stage
        if stage_name in ("exact", "tolerance", "many_to_one"):
            row = conn.execute(
                f"SELECT COUNT(*), COALESCE(SUM(amount_inr), 0) "
                f"FROM {result_table} WHERE run_id = '{run_id}' AND stage = '{stage_name}'"
            ).fetchone()
        elif stage_name in ("classify", "orphans", "duplicates", "status_mismatch"):
            row = conn.execute(
                f"SELECT COUNT(*), COALESCE(SUM(amount_inr), 0) "
                f"FROM {result_table} WHERE run_id = '{run_id}'"
            ).fetchone()
        elif stage_name == "root_causes":
            row = conn.execute(
                f"SELECT COUNT(*), COALESCE(SUM(rupees_at_risk), 0) "
                f"FROM {result_table} WHERE run_id = '{run_id}'"
            ).fetchone()
        elif stage_name == "priority":
            row = conn.execute(
                f"SELECT COUNT(*), COALESCE(SUM(rupees_at_risk), 0) "
                f"FROM breaks WHERE run_id = '{run_id}'"
            ).fetchone()
        else:
            row = (0, 0)

        count = int(row[0])
        rupees = float(row[1])

        print(f"{stage_name:<20} {count:>12,} {rupees:>18,.2f} {elapsed:>9.2f}s")

        # Log to match_stage_log
        try:
            conn.execute(
                f"INSERT INTO match_stage_log "
                f"(run_id, stage, started_at, elapsed_ms, rows_in, rows_matched, rupees_matched) "
                f"VALUES ('{run_id}', '{stage_name}', NOW(), "
                f"{int(elapsed * 1000)}, 0, {count}, {rupees})"
            )
        except pyexasol.ExaQueryError:
            pass  # non-critical

    print("-" * 64)
    print(f"{'TOTAL':<20} {'':>12} {'':>18} {total_time:>9.2f}s")

    # Summary
    total_matched = conn.execute(
        f"SELECT COUNT(*) FROM matches WHERE run_id = '{run_id}'"
    ).fetchval()
    total_breaks = conn.execute(
        f"SELECT COUNT(*) FROM breaks WHERE run_id = '{run_id}'"
    ).fetchval()
    npci_total = conn.execute("SELECT COUNT(*) FROM npci_settlement").fetchval()

    auto_match_rate = (int(total_matched) / max(int(npci_total), 1)) * 100
    print(f"\nAuto-match rate: {auto_match_rate:.1f}%")
    print(f"Total matched: {int(total_matched):,}")
    print(f"Total breaks: {int(total_breaks):,}")

    conn.close()
    return run_id


def main() -> None:
    """CLI entry point."""
    run_engine()


if __name__ == "__main__":
    main()
