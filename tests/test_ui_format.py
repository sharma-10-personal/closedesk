"""Indian rupee formatting used by the investigator UI."""

from closedesk.app.ui import fmt_inr, fmt_inr_short


def test_indian_grouping() -> None:
    assert fmt_inr(1234567.89) == "₹12,34,567.89"
    assert fmt_inr(999.5) == "₹999.50"
    assert fmt_inr(1000) == "₹1,000.00"
    assert fmt_inr(100000) == "₹1,00,000.00"


def test_short_rupees() -> None:
    assert fmt_inr_short(12_34_56_789) == "₹12.35 Cr"
    assert fmt_inr_short(12_34_567) == "₹12.35 L"
    assert fmt_inr_short(999) == "₹999.00"
