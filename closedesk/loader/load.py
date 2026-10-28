"""Bulk load synthetic CSVs into Exasol via pyexasol."""

from __future__ import annotations

import csv
import time
from pathlib import Path

import pyexasol
from dotenv import dotenv_values

TABLE_CSV_MAP = {
    "NPCI_SETTLEMENT": "npci_settlement.csv",
    "BANK_LEDGER": "bank_ledger.csv",
    "MERCHANT_RECORDS": "merchant_records.csv",
    "ANSWER_KEY": "answer_key.csv",
}


def _connect(env: dict[str, str | None]) -> pyexasol.ExaConnection:
    """Open pyexasol connection from env vars."""
    return pyexasol.connect(
        dsn=env.get("EXA_DSN", "localhost:8563"),
        user=env.get("EXA_USER", "sys"),
        password=env.get("EXA_PASSWORD", ""),
        schema=env.get("EXA_SCHEMA", "CLOSEDESK"),
        compression=True,
        websocket_sslopt={"cert_reqs": 0},
    )


def _csv_rows(path: Path) -> list[tuple[str, ...]]:
    """Read a CSV (skip header) and return list of tuples."""
    with open(path, newline="") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        return [tuple(row) for row in reader]


def load(data_dir: Path | None = None, env_path: Path | None = None) -> None:
    """Load all four CSVs into Exasol. Truncates first for idempotent reruns."""
    data_dir = data_dir or Path("data")
    env = dotenv_values(env_path or Path(".env"))

    conn = _connect(env)
    schema = env.get("EXA_SCHEMA", "CLOSEDESK")
    conn.execute(f"OPEN SCHEMA {schema}")

    for table, csv_file in TABLE_CSV_MAP.items():
        csv_path = data_dir / csv_file
        if not csv_path.exists():
            print(f"SKIP {table}: {csv_path} not found")
            continue

        rows = _csv_rows(csv_path)
        print(f"Loading {len(rows):,} rows into {table}...")

        conn.execute(f"TRUNCATE TABLE {table}")

        t0 = time.perf_counter()
        conn.import_from_iterable(rows, table)
        elapsed = time.perf_counter() - t0

        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchval()
        print(f"  {table}: {count:,} rows loaded in {elapsed:.2f}s")

    conn.close()
    print("Load complete.")


def main() -> None:
    """CLI entry point."""
    load()


if __name__ == "__main__":
    main()
