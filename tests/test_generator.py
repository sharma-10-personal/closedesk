"""Test the synthetic generator at small scale."""

import csv
import tempfile
from pathlib import Path

import yaml

from closedesk.generator.build import generate


def test_generator_produces_four_files():
    """Generate 1000-row data and verify structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir)
        # Write a small scenario
        scenario = {
            "version": 1,
            "name": "test",
            "seed": 42,
            "iso_date": "2026-10-27",
            "rows_per_source": 1000,
            "breaks": {
                "timing_skew": 0.012,
                "duplicate_ledger": 0.004,
                "amount_mismatch": 0.003,
                "missing_settlement": 0.005,
                "failed_but_debited": 0.006,
                "reversal_not_posted": 0.002,
                "many_to_one_batch": 0.008,
            },
            "tolerance": {"amount_inr": 1.0, "time_seconds": 300},
            "acquiring_bank": {"name": "Test Bank", "ifsc_prefix": "TSTB"},
            "calibration": {
                "npci_upi_month": "September 2026",
                "npci_upi_volume_million": 24068.38,
                "npci_upi_value_crore": 2937396.67,
                "npci_upi_banks_live": 756,
                "npci_upi_source": "https://www.npci.org.in/product/upi/product-statistics",
                "npci_upi_source_note": "Test",
            },
        }
        scenario_path = out / "scenario.yaml"
        scenario_path.write_text(yaml.dump(scenario))

        generate(scenario_path=scenario_path, out_dir=out)

        # All 4 files exist and are non-empty
        for name in [
            "npci_settlement.csv",
            "bank_ledger.csv",
            "merchant_records.csv",
            "answer_key.csv",
        ]:
            p = out / name
            assert p.exists(), f"{name} missing"
            assert p.stat().st_size > 100, f"{name} too small"

        # Answer key has rows for every break type
        with open(out / "answer_key.csv") as f:
            reader = csv.DictReader(f)
            ak_rows = list(reader)

        types_found = {r["break_type"] for r in ak_rows}
        expected_types = {
            "timing_skew",
            "duplicate_ledger",
            "amount_mismatch",
            "missing_settlement",
            "failed_but_debited",
            "reversal_not_posted",
            "many_to_one_batch",
        }
        assert expected_types.issubset(types_found), f"Missing: {expected_types - types_found}"

        # Every npci_ref in answer_key exists in at least one source file
        npci_refs_ak = {r["npci_ref"] for r in ak_rows}

        all_refs: set[str] = set()
        for name in ["npci_settlement.csv", "bank_ledger.csv", "merchant_records.csv"]:
            with open(out / name) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ref = row.get("npci_ref", "")
                    if ref:
                        all_refs.add(ref)

        orphans = npci_refs_ak - all_refs
        assert len(orphans) == 0, f"Answer key refs not in any source: {orphans}"

        # Total breaks roughly match config (within ±50% at 1000 rows)
        expected_total = sum(int(1000 * v) for v in scenario["breaks"].values())
        assert len(ak_rows) >= expected_total * 0.5, "Too few breaks planted"
        assert len(ak_rows) <= expected_total * 2.0, "Too many breaks planted"
