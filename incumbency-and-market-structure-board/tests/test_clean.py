"""Unit tests for deterministic cleaning helpers (Milestone 2)."""

from datetime import date

from incumbency import clean


def test_parse_value_handles_money_formats():
    assert clean.parse_value("$1,234.50") == 1234.50
    assert clean.parse_value("1234.5") == 1234.5
    assert clean.parse_value(1000) == 1000.0
    assert clean.parse_value("(500)") == -500.0  # accounting-style negative
    assert clean.parse_value("") is None
    assert clean.parse_value(None) is None
    assert clean.parse_value("n/a") is None


def test_parse_bids():
    assert clean.parse_bids("1") == 1
    assert clean.parse_bids(3) == 3
    assert clean.parse_bids("12 bids") == 12
    assert clean.parse_bids("") is None
    assert clean.parse_bids(None) is None
    assert clean.parse_bids("-1") is None       # negative is invalid
    assert clean.parse_bids(True) is None        # bool guard
    assert clean.parse_bids("0") == 0


def test_normalize_currency_null_is_cad():
    assert clean.normalize_currency(None) == "CAD"
    assert clean.normalize_currency("") == "CAD"
    assert clean.normalize_currency("usd") == "USD"


def test_parse_date_formats():
    assert clean.parse_date("2024-03-04") == date(2024, 3, 4)
    assert clean.parse_date("2024/03/04") == date(2024, 3, 4)
    assert clean.parse_date("2024-03-04T10:30:00") == date(2024, 3, 4)
    assert clean.parse_date("bad-date") is None
    assert clean.parse_date(None) is None


def test_amendment_classification():
    assert clean.is_amendment("000") is False
    assert clean.is_amendment("001") is True
    assert clean.is_amendment(None) is False
    # admin by keyword
    assert clean.is_admin_amendment("Administrative correction", "002", 50_000) is True
    # financial increase is not admin
    assert clean.is_admin_amendment("Increase to contract value", "001", 50_000) is False
    # fallback: amendment with zero value delta is admin when type unknown
    assert clean.is_admin_amendment("", "001", 0.0) is True
    assert clean.is_admin_amendment("", "001", 5000.0) is False


def test_value_conflict_detection():
    assert clean.detect_value_conflict(275_000, 412_000) is True
    assert clean.detect_value_conflict(100_000, 100_500) is False  # within tolerance
    assert clean.detect_value_conflict(100_000, None) is False     # one side missing
