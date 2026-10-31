"""Upload validation rejects bad settlement files before they reach Exasol."""

from closedesk.app.ui import validate_csv
from closedesk.generator.build import NPCI_HEADERS

HEADER = ",".join(NPCI_HEADERS)
ROW = "UPI1,2026-10-27 10:00:00.000,100.00,SUCCESS,SBI,HDFC,M1,5411,GW01"


def test_valid_file() -> None:
    data = f"{HEADER}\n{ROW}\n{ROW.replace('UPI1', 'UPI2')}\n".encode()
    assert validate_csv(data, NPCI_HEADERS) == (2, None)


def test_wrong_header() -> None:
    rows, error = validate_csv(b"a,b,c\n1,2,3\n", NPCI_HEADERS)
    assert rows == 0
    assert error and error.startswith("Header must be")


def test_bad_amount() -> None:
    data = f"{HEADER}\n{ROW.replace('100.00', 'abc')}\n".encode()
    _rows, error = validate_csv(data, NPCI_HEADERS)
    assert error and "amount_inr" in error


def test_duplicate_key() -> None:
    data = f"{HEADER}\n{ROW}\n{ROW}\n".encode()
    _rows, error = validate_csv(data, NPCI_HEADERS)
    assert error and "duplicate" in error
