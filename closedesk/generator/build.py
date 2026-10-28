"""Synthetic NPCI / ledger / merchant generator with planted breaks and answer key."""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

# --- Constants ---

BANKS = ["SBI", "HDFC", "ICICI", "Axis", "Kotak", "Yes", "PNB", "BOB"]
MCCS = ["5411", "5541", "5812", "5999", "4121", "5691", "7011", "5311"]
GATEWAYS = ["GW01", "GW02", "GW03", "GW04", "GW05"]

NPCI_HEADERS = [
    "npci_ref", "txn_ts", "amount_inr", "status",
    "payer_psp", "payee_psp", "merchant_id", "mcc", "gateway_id",
]
LEDGER_HEADERS = [
    "ledger_id", "npci_ref", "txn_ts", "amount_inr",
    "direction", "account_id", "status", "posting_ts",
]
MERCHANT_HEADERS = [
    "merchant_txn_id", "npci_ref", "txn_ts", "amount_inr",
    "merchant_id", "gateway_id", "status",
]
ANSWER_KEY_HEADERS = ["break_id", "npci_ref", "break_type", "expected_action"]


@dataclass
class Txn:
    """One good base transaction across all three sources."""

    npci_ref: str
    txn_ts: datetime
    amount_inr: float
    payer_psp: str
    payee_psp: str
    merchant_id: str
    mcc: str
    gateway_id: str
    ledger_id: str
    account_id: str
    posting_ts: datetime
    merchant_txn_id: str
    # Mutable rows that will be written to CSV. Set after generation.
    npci_row: list[Any] = field(default_factory=list)
    ledger_row: list[Any] = field(default_factory=list)
    merchant_row: list[Any] = field(default_factory=list)
    # If this txn has a break applied
    break_type: str | None = None


def _ts_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _make_npci_ref(idx: int, iso_date: str) -> str:
    d = iso_date.replace("-", "")
    return f"UPI{d}{idx:08d}"


def _generate_base_transactions(
    rng: random.Random, n: int, iso_date: str
) -> list[Txn]:
    """Generate n good transactions for the given date."""
    print(f"Generating {n:,} base transactions...")
    base_dt = datetime.strptime(iso_date, "%Y-%m-%d")
    day_seconds = 86399

    txns: list[Txn] = []
    for i in range(n):
        sec = rng.randint(0, day_seconds)
        txn_ts = base_dt + timedelta(seconds=sec, microseconds=rng.randint(0, 999999))
        amount = round(rng.uniform(10.0, 99999.0), 2)
        merchant_id = f"M{rng.randint(100000, 999999)}"
        gateway_id = rng.choice(GATEWAYS)
        posting_offset = rng.randint(0, 60)

        t = Txn(
            npci_ref=_make_npci_ref(i, iso_date),
            txn_ts=txn_ts,
            amount_inr=amount,
            payer_psp=rng.choice(BANKS),
            payee_psp=rng.choice(BANKS),
            merchant_id=merchant_id,
            mcc=rng.choice(MCCS),
            gateway_id=gateway_id,
            ledger_id=f"L{i:012d}",
            account_id=f"A{rng.randint(10000000, 99999999)}",
            posting_ts=txn_ts + timedelta(seconds=posting_offset),
            merchant_txn_id=f"MT{i:012d}",
        )

        # Small jitter on ledger and merchant timestamps (good rows, within tolerance)
        ledger_ts = txn_ts + timedelta(seconds=rng.randint(0, 10))
        merchant_ts = txn_ts + timedelta(seconds=rng.randint(0, 8))

        t.npci_row = [
            t.npci_ref, _ts_str(txn_ts), f"{amount:.2f}", "SUCCESS",
            t.payer_psp, t.payee_psp, merchant_id, t.mcc, gateway_id,
        ]
        t.ledger_row = [
            t.ledger_id, t.npci_ref, _ts_str(ledger_ts), f"{amount:.2f}",
            "CREDIT", t.account_id, "POSTED", _ts_str(t.posting_ts),
        ]
        t.merchant_row = [
            t.merchant_txn_id, t.npci_ref, _ts_str(merchant_ts), f"{amount:.2f}",
            merchant_id, gateway_id, "SUCCESS",
        ]
        txns.append(t)

    return txns


def _pick_indices(rng: random.Random, pool: list[int], count: int) -> list[int]:
    """Pick `count` indices from pool without replacement, removing them from pool."""
    chosen = rng.sample(pool, min(count, len(pool)))
    for c in chosen:
        pool.remove(c)
    return chosen


def _plant_breaks(
    rng: random.Random,
    txns: list[Txn],
    breaks_cfg: dict[str, float],
    iso_date: str,
) -> list[list[str]]:
    """Mutate transactions to plant breaks. Returns answer_key rows."""
    n = len(txns)
    available = list(range(n))
    rng.shuffle(available)
    answer_key: list[list[str]] = []
    extra_ledger_rows: list[list[Any]] = []
    break_counter = 0

    def _bid() -> str:
        nonlocal break_counter
        break_counter += 1
        return f"BK{break_counter:08d}"

    # 1. timing_skew
    count = int(n * breaks_cfg.get("timing_skew", 0))
    indices = _pick_indices(rng, available, count)
    print(f"Planting {len(indices):,} timing_skew breaks...")
    for i in indices:
        t = txns[i]
        t.break_type = "timing_skew"
        shift_ledger = rng.randint(360, 900)  # 6-15 min
        shift_merchant = rng.randint(180, 480)  # 3-8 min
        new_ledger_ts = t.txn_ts + timedelta(seconds=shift_ledger)
        new_merchant_ts = t.txn_ts + timedelta(seconds=shift_merchant)
        t.ledger_row[2] = _ts_str(new_ledger_ts)
        t.merchant_row[2] = _ts_str(new_merchant_ts)
        answer_key.append([_bid(), t.npci_ref, "timing_skew", "widen_tolerance"])

    # 2. duplicate_ledger
    count = int(n * breaks_cfg.get("duplicate_ledger", 0))
    indices = _pick_indices(rng, available, count)
    print(f"Planting {len(indices):,} duplicate_ledger breaks...")
    for i in indices:
        t = txns[i]
        t.break_type = "duplicate_ledger"
        dup_ledger_id = f"LDUP{i:010d}"
        dup_row = list(t.ledger_row)
        dup_row[0] = dup_ledger_id
        extra_ledger_rows.append(dup_row)
        answer_key.append([_bid(), t.npci_ref, "duplicate_ledger", "flag_duplicate"])

    # 3. amount_mismatch
    count = int(n * breaks_cfg.get("amount_mismatch", 0))
    indices = _pick_indices(rng, available, count)
    print(f"Planting {len(indices):,} amount_mismatch breaks...")
    for i in indices:
        t = txns[i]
        t.break_type = "amount_mismatch"
        delta = round(rng.uniform(2.0, 50.0), 2)
        original = float(t.merchant_row[3])
        t.merchant_row[3] = f"{original + delta:.2f}"
        answer_key.append([_bid(), t.npci_ref, "amount_mismatch", "notify_merchant_mismatch"])

    # 4. missing_settlement
    count = int(n * breaks_cfg.get("missing_settlement", 0))
    indices = _pick_indices(rng, available, count)
    print(f"Planting {len(indices):,} missing_settlement breaks...")
    for i in indices:
        t = txns[i]
        t.break_type = "missing_settlement"
        t.npci_row = []  # will be skipped when writing
        answer_key.append([_bid(), t.npci_ref, "missing_settlement", "no_action_explain"])

    # 5. failed_but_debited
    count = int(n * breaks_cfg.get("failed_but_debited", 0))
    indices = _pick_indices(rng, available, count)
    print(f"Planting {len(indices):,} failed_but_debited breaks...")
    for i in indices:
        t = txns[i]
        t.break_type = "failed_but_debited"
        t.npci_row[3] = "FAILED"  # status
        t.ledger_row[4] = "DEBIT"  # direction
        t.merchant_row = []  # delete merchant record
        answer_key.append([_bid(), t.npci_ref, "failed_but_debited", "reverse_failed_debit"])

    # 6. reversal_not_posted
    count = int(n * breaks_cfg.get("reversal_not_posted", 0))
    indices = _pick_indices(rng, available, count)
    print(f"Planting {len(indices):,} reversal_not_posted breaks...")
    for i in indices:
        t = txns[i]
        t.break_type = "reversal_not_posted"
        t.npci_row[3] = "REVERSED"  # status
        # ledger still shows CREDIT / POSTED — that's the problem
        answer_key.append([_bid(), t.npci_ref, "reversal_not_posted", "post_missing_credit"])

    # 7. many_to_one_batch
    batch_frac = breaks_cfg.get("many_to_one_batch", 0)
    batch_target = int(n * batch_frac)
    # Force groups: assign the same merchant_id to consecutive available txns
    # so we always have enough groups, even at small N.
    batched = 0
    batch_size = 3
    print(f"Planting ~{batch_target:,} many_to_one_batch breaks...")
    while batched < batch_target and len(available) >= batch_size:
        batch_idxs = available[:batch_size]
        # Give them all the same merchant_id so the batch makes sense
        shared_mid = txns[batch_idxs[0]].merchant_id
        for bi in batch_idxs:
            txns[bi].merchant_id = shared_mid
            txns[bi].merchant_row[4] = shared_mid

        total_amount = sum(float(txns[bi].npci_row[2]) for bi in batch_idxs)
        batch_npci_ref = f"BATCH{iso_date.replace('-', '')}{batched:06d}"
        first = txns[batch_idxs[0]]
        batch_npci_row = [
            batch_npci_ref, first.npci_row[1], f"{total_amount:.2f}", "SUCCESS",
            first.payer_psp, first.payee_psp, shared_mid, first.mcc, first.gateway_id,
        ]

        for bi in batch_idxs:
            t = txns[bi]
            t.break_type = "many_to_one_batch"
            t.npci_row = []  # remove individual NPCI rows
            t.ledger_row[1] = batch_npci_ref  # point ledger to batch ref
            t.merchant_row[1] = batch_npci_ref  # point merchant to batch ref
            if bi in available:
                available.remove(bi)
            answer_key.append([_bid(), batch_npci_ref, "many_to_one_batch", "no_action_explain"])
            batched += 1

        # Store the batch NPCI row on the first txn
        txns[batch_idxs[0]].npci_row = batch_npci_row

    print(f"Total breaks planted: {len(answer_key):,}")
    return answer_key, extra_ledger_rows


def _write_csvs(
    out_dir: Path,
    txns: list[Txn],
    answer_key: list[list[str]],
    extra_ledger_rows: list[list[Any]],
) -> None:
    """Write the four CSV files."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # NPCI
    npci_path = out_dir / "npci_settlement.csv"
    with open(npci_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(NPCI_HEADERS)
        for t in txns:
            if t.npci_row:
                w.writerow(t.npci_row)
    npci_count = sum(1 for t in txns if t.npci_row)
    print(f"Wrote {npci_count:,} rows to {npci_path}")

    # Bank ledger
    ledger_path = out_dir / "bank_ledger.csv"
    with open(ledger_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(LEDGER_HEADERS)
        for t in txns:
            if t.ledger_row:
                w.writerow(t.ledger_row)
        for row in extra_ledger_rows:
            w.writerow(row)
    ledger_count = sum(1 for t in txns if t.ledger_row) + len(extra_ledger_rows)
    print(f"Wrote {ledger_count:,} rows to {ledger_path}")

    # Merchant
    merchant_path = out_dir / "merchant_records.csv"
    with open(merchant_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(MERCHANT_HEADERS)
        for t in txns:
            if t.merchant_row:
                w.writerow(t.merchant_row)
    merchant_count = sum(1 for t in txns if t.merchant_row)
    print(f"Wrote {merchant_count:,} rows to {merchant_path}")

    # Answer key
    ak_path = out_dir / "answer_key.csv"
    with open(ak_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(ANSWER_KEY_HEADERS)
        for row in answer_key:
            w.writerow(row)
    print(f"Wrote {len(answer_key):,} rows to {ak_path}")


def generate(scenario_path: Path | None = None, out_dir: Path | None = None) -> Path:
    """Run the full generation pipeline. Returns the output directory."""
    scenario_path = scenario_path or Path("config/scenario.yaml")
    cfg: dict[str, Any] = yaml.safe_load(scenario_path.read_text())

    seed: int = cfg["seed"]
    iso_date: str = cfg["iso_date"]
    n: int = cfg["rows_per_source"]
    breaks_cfg: dict[str, float] = cfg["breaks"]

    out = out_dir or Path("data")
    rng = random.Random(seed)

    txns = _generate_base_transactions(rng, n, iso_date)
    answer_key, extra_ledger_rows = _plant_breaks(rng, txns, breaks_cfg, iso_date)
    _write_csvs(out, txns, answer_key, extra_ledger_rows)

    print("Generation complete.")
    return out


def main() -> None:
    """CLI entry point."""
    generate()


if __name__ == "__main__":
    main()
