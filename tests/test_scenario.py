from pathlib import Path

import yaml


def test_break_mix_is_a_small_fraction():
    raw = yaml.safe_load(Path("config/scenario.yaml").read_text())
    total = sum(raw["breaks"].values())
    assert 0 < total < 0.2
    assert raw["rows_per_source"] >= 1_000_000
    assert raw["calibration"]["npci_upi_source_note"]
