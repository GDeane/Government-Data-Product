"""Tests for the 'who's my competition' rescope: top-k shares, the vendor share table, and
RFP -> historical-market linkage."""

from datetime import date

from incumbency import fixtures, linkage, pipeline, signals

TODAY = date(2026, 6, 15)


def test_topk_shares_ranks_by_value():
    vbv = {"A": 800.0, "B": 150.0, "C": 50.0}
    topk = signals.topk_shares(vbv, k=3)
    assert [v for v, _ in topk] == ["A", "B", "C"]
    assert round(topk[0][1], 3) == 0.8
    # k larger than the field just returns what exists.
    assert len(signals.topk_shares(vbv, k=10)) == 3


def _market(gsin="D302A"):
    res = pipeline.run_pipeline(fixtures.generate_raw_awards(), today=TODAY)
    return res.markets[res.markets["gsin"] == gsin].iloc[0]


def test_vendor_share_table_sums_to_one_both_bases():
    row = _market("D302A")
    shares = row["vendor_shares"]
    assert round(sum(s["value_share"] for s in shares), 3) == 1.0
    assert round(sum(s["count_share"] for s in shares), 3) == 1.0
    # sorted by value share descending
    vs = [s["value_share"] for s in shares]
    assert vs == sorted(vs, reverse=True)


def test_compute_markets_emits_top2_top3():
    row = _market("D302A")
    assert row["top1_vendor"] and row["top2_vendor"] and row["top3_vendor"]
    assert row["top1_share"] >= row["top2_share"] >= row["top3_share"]


def test_market_keyed_on_unspsc():
    """With UNSPSC present, the market commodity key is the UNSPSC, not the GSIN (D10)."""
    row = _market("D302A")  # representative GSIN is still D302A...
    assert row["commodity_type"] == "unspsc"
    assert row["commodity"] == "80101500"   # ...but the key is the UNSPSC


def test_rfp_linkage_exact_commodity_and_none():
    res = pipeline.run_pipeline(fixtures.generate_raw_awards(), today=TODAY)
    markets = res.markets
    rfps = pipeline.build_rfps(fixtures.generate_open_tenders())

    by_sol = {r["solicitation_number"]: r for _, r in rfps.iterrows()}

    def match(sol):
        r = by_sol[sol]
        return linkage.match_rfp_to_markets(r["unspsc"], r["gsin"], r["buyer_canonical"],
                                            markets)

    # D302A / PSPC RFP (UNSPSC 80101500) -> exact match, joined on UNSPSC.
    m1 = match("OPEN-2026-001")
    assert m1.precision == "exact" and len(m1.markets) == 1
    assert m1.markets.iloc[0]["commodity"] == "80101500"
    assert "unspsc" in m1.matched_on

    # Commodity with no history -> none.
    assert match("OPEN-2026-003").precision == "none"
    # No commodity code at all -> cannot link.
    assert match("OPEN-2026-004").precision == "none"


def test_rfp_links_by_gsin_when_no_unspsc():
    """A notice carrying only a GSIN (no UNSPSC) still links via the GSIN fallback join."""
    markets = pipeline.run_pipeline(fixtures.generate_raw_awards(), today=TODAY).markets
    m = linkage.match_rfp_to_markets("", "D302A",
                                     "Public Services and Procurement Canada", markets)
    assert m.precision == "exact" and m.matched_on == "gsin"
    assert m.markets.iloc[0]["commodity"] == "80101500"


def test_rfp_buyer_canonicalization():
    """An RFP posted under the 'PSPC' abbreviation must canonicalize to the same buyer as
    the historical market so the link is exact, not just gsin-level."""
    rfps = pipeline.build_rfps(fixtures.generate_open_tenders())
    pspc = rfps[rfps["solicitation_number"] == "OPEN-2026-001"].iloc[0]
    assert pspc["buyer_canonical"] == "Public Services and Procurement Canada"


def test_commodity_only_match_when_buyer_differs():
    markets = pipeline.run_pipeline(fixtures.generate_raw_awards(), today=TODAY).markets
    # Same commodity (UNSPSC) as a real market but a buyer that won't canonicalize to it.
    m = linkage.match_rfp_to_markets("80101500", "", "Some Other Department", markets)
    assert m.precision == "commodity" and not m.markets.empty
