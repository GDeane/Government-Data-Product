"""Offline tests for the CanadaBuys contract-history mapping and the empty-GSIN guard.

These exercise the amendment-aware spine without network by constructing a tiny frame in the
real contract-history column shape."""

from datetime import date

import pandas as pd

from incumbency import pipeline
from incumbency.ingest import _CH_COLS, map_contract_history


def _ch_row(**kw):
    """Build a contract-history-shaped row; keys are the short names from _CH_COLS."""
    row = {col: "" for col in _CH_COLS.values()}
    for short, val in kw.items():
        row[_CH_COLS[short]] = val
    return row


def test_map_contract_history_vendor_fallback_and_amendments():
    raw = pd.DataFrame([
        # standardized name present
        _ch_row(procurement="W1-001", supplier_std="ACME INC", supplier_legal="Acme Incorp",
                entity="PSPC", gsin="D302A", procedure="Competitive - Open bidding",
                instrument="Contract", amount="100000", amd_num="000",
                award_date="2024-01-10"),
        # standardized blank -> fall back to legal name
        _ch_row(procurement="W1-002", supplier_std="", supplier_legal="Globex Ltd",
                entity="PSPC", gsin="D302A", procedure="Non-competitive",
                instrument="Standing Offer", amount="50000", amd_num="000",
                award_date="2024-03-05"),
        # an amendment row on the first contract
        _ch_row(procurement="W1-001", supplier_std="ACME INC", entity="PSPC", gsin="D302A",
                procedure="Competitive - Open bidding", instrument="Contract",
                amount="20000", amd_num="001", amd_type="Increase to contract value",
                award_date="2024-06-01"),
    ])
    mapped = map_contract_history(raw)
    assert list(mapped["vendorName"]) == ["ACME INC", "Globex Ltd", "ACME INC"]
    assert list(mapped["solicitationNumber"]) == ["W1-001", "W1-002", "W1-001"]
    assert list(mapped["numberOfBids"]) == [None, None, None]  # never fabricated

    # Run through the pipeline: the amendment must not count as a separate award event.
    res = pipeline.run_pipeline(mapped, today=date(2024, 12, 31))
    awards = res.awards
    assert int(awards["is_amendment"].sum()) == 1
    d302a = res.markets[res.markets["gsin"] == "D302A"].iloc[0]
    assert d302a["n_awards"] == 2          # two base awards, not three rows
    assert d302a["bid_signal"] == "none"   # no bids on this spine


def test_empty_gsin_groups_are_skipped():
    raw = pd.DataFrame([
        _ch_row(procurement="W2-001", supplier_std="A Co", entity="PSPC", gsin="",
                procedure="Competitive - Open bidding", instrument="Contract",
                amount="100000", amd_num="000", award_date="2024-01-10"),
        _ch_row(procurement="W2-002", supplier_std="B Co", entity="PSPC", gsin="",
                procedure="Competitive - Open bidding", instrument="Contract",
                amount="100000", amd_num="000", award_date="2024-02-10"),
    ])
    res = pipeline.run_pipeline(map_contract_history(raw), today=date(2024, 12, 31))
    # No market should be produced from blank-GSIN rows.
    assert res.markets.empty or (res.markets["gsin"].str.strip() != "").all()
