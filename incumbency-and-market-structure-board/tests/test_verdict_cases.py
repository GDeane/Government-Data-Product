"""Golden end-to-end verdict cases (D6.1) — the demo's load-bearing behaviour.

Runs the FULL pipeline on the synthetic fixtures and asserts each engineered market lands on
its intended verdict, including the two bid-count disambiguations (D7) and the market that
honestly stays ambiguous for lack of post-mandate coverage."""

from datetime import date

import pytest

from incumbency import fixtures, pipeline

TODAY = date(2026, 6, 15)


@pytest.fixture(scope="module")
def markets():
    res = pipeline.run_pipeline(fixtures.generate_raw_awards(), today=TODAY)
    return {(r["gsin"], r["buyer_canonical"]): r for _, r in res.markets.iterrows()}


def _m(markets, gsin):
    hits = [v for k, v in markets.items() if k[0] == gsin]
    assert hits, f"market {gsin} not found"
    return hits[0]


def test_enterable_dynamic(markets):
    m = _m(markets, "D302A")
    assert m["verdict"] == "enterable"
    assert m["top1_share"] >= 0.65          # concentrated...
    assert m["distinct_winners"] >= 2 and m["lead_changes"] >= 1  # ...but dynamic


def test_walled_lockin(markets):
    m = _m(markets, "R019C")
    assert m["verdict"] == "walled"
    assert m["lockin_share"] >= 0.5


def test_ambiguous_no_bid_coverage(markets):
    m = _m(markets, "N7030")
    assert m["verdict"] == "ambiguous"
    assert m["bid_signal"] == "none"        # all pre-mandate, so genuinely undecidable
    assert m["ambiguity_note"]


def test_enterable_thin_field_via_single_bid(markets):
    m = _m(markets, "J5005")
    assert m["verdict"] == "enterable"
    assert m["top1_share"] >= 0.65          # concentrated + low turnover...
    assert m["single_bid_rate"] >= 0.5      # ...but incumbent wins unopposed


def test_walled_strong_incumbent_via_many_bids(markets):
    m = _m(markets, "V1124")
    assert m["verdict"] == "walled"
    assert m["top1_share"] >= 0.65
    assert m["single_bid_rate"] <= 0.25     # consistently beats real rivals


def test_insufficient_data(markets):
    m = _m(markets, "L0998")
    assert m["verdict"] == "insufficient_data"


def test_enterable_fragmented(markets):
    m = _m(markets, "B0079")
    assert m["verdict"] == "enterable"
    assert m["top1_share"] < 0.65           # no entrenched incumbent
    # the unresolved near-duplicate pair surfaces for human judgement (D3.3)
    assert any("Riverbend" in a for a, b, _ in m["possible_same_vendor"])
