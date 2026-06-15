"""Unit tests for concentration, turnover, bid metrics, score, and verdict logic (M4/D7)."""

from datetime import date

import pandas as pd

from incumbency import signals


def _award(vendor, value, d, *, proc="open_competitive", instr="contract",
           bids=None, post=False, amend=False, admin=False):
    return {
        "vendor_canonical": vendor, "award_value_cad": value,
        "award_date": date.fromisoformat(d) if d else None,
        "procedure_class": proc, "instrument_class": instr,
        "num_bids": bids, "has_bid_count": bids is not None, "post_mandate": post,
        "is_amendment": amend, "is_admin_amendment": admin,
    }


def test_concentration_metrics():
    vbv = {"A": 800.0, "B": 100.0, "C": 100.0}
    assert signals.top1_share(vbv) == 0.8
    assert signals.top1_vendor(vbv) == "A"
    assert round(signals.hhi(vbv), 4) == round(0.8**2 + 0.1**2 + 0.1**2, 4)


def test_turnover_lead_changes_and_new_entrant():
    df = pd.DataFrame([
        _award("B", 300, "2019-01-01"),
        _award("B", 200, "2020-01-01"),
        _award("A", 600, "2021-01-01"),   # A overtakes B in cumulative value -> 1 lead change
        _award("A", 100, "2022-01-01"),
        _award("C", 100, "2023-01-01"),   # new entrant C
    ])
    tm = signals.turnover_metrics(df, today=date(2024, 1, 1))
    assert tm.distinct_winners == 3
    assert tm.lead_changes == 1
    assert tm.last_new_entrant_date == date(2023, 1, 1)


def test_admin_amendments_excluded_from_value():
    df = pd.DataFrame([
        _award("A", 1000, "2023-01-01"),
        _award("A", 500, "2023-06-01", amend=True, admin=True),  # admin -> excluded
    ])
    vbv = signals.value_by_vendor(df)
    assert vbv["A"] == 1000


def test_bid_metrics_single_bid_rate():
    df = pd.DataFrame([
        _award("A", 100, "2021-01-01"),                       # pre-mandate, no count
        _award("A", 100, "2023-09-01", bids=1, post=True),
        _award("A", 100, "2024-01-01", bids=1, post=True),
        _award("A", 100, "2024-06-01", bids=2, post=True),
    ])
    bm = signals.bid_metrics(df)
    assert bm.post_mandate_awards == 3
    assert bm.covered_awards == 3
    assert bm.single_bid_rate == round(2 / 3, 4)
    assert bm.signal == "strong"


def test_bid_metrics_no_coverage():
    df = pd.DataFrame([_award("A", 100, "2019-01-01"), _award("A", 100, "2020-01-01")])
    bm = signals.bid_metrics(df)
    assert bm.signal == "none"
    assert bm.single_bid_rate is None


def test_score_weights_sum_to_one_and_bounded():
    s = signals.contestability_score(open_sh=1.0, lockin_sh=0.0, tnorm=1.0)
    assert s == 100.0
    s0 = signals.contestability_score(open_sh=0.0, lockin_sh=1.0, tnorm=0.0)
    assert s0 == 0.0


def _verdict(df, today=date(2026, 1, 1)):
    vbv = signals.value_by_vendor(df)
    pmix = signals.procedure_mix(df)
    imix = signals.instrument_mix(df)
    tm = signals.turnover_metrics(df, today=today)
    bm = signals.bid_metrics(df)
    n = int(df[~df["is_amendment"] & ~df["is_admin_amendment"]].shape[0])
    return signals.decide_verdict(n_awards=n, top1=signals.top1_share(vbv),
                                  pmix=pmix, imix=imix, tm=tm, bm=bm)


def test_verdict_high_single_bid_resolves_to_enterable_thin_field():
    # Concentrated, open, no turnover, but mostly single-bid post-mandate -> thin field.
    rows = [_award("A", 100, f"202{i}-09-01", bids=1, post=True) for i in range(3, 6)]
    rows += [_award("A", 100, "2021-01-01"), _award("A", 100, "2022-01-01")]
    v = _verdict(pd.DataFrame(rows))
    assert v.verdict == "enterable"
    assert "UNOPPOSED" in v.reason or "thin field" in v.reason.lower()


def test_verdict_low_single_bid_resolves_to_walled_strong_incumbent():
    rows = [_award("A", 100, f"202{i}-09-01", bids=7, post=True) for i in range(3, 6)]
    rows += [_award("A", 100, "2021-01-01"), _award("A", 100, "2022-01-01")]
    v = _verdict(pd.DataFrame(rows))
    assert v.verdict == "walled"
    assert "STRONG" in v.reason or "rivals" in v.reason.lower()


def test_verdict_no_coverage_stays_ambiguous():
    # Concentrated, open, no turnover, all pre-mandate -> genuinely ambiguous.
    rows = [_award("A", 100, f"201{i}-01-01") for i in range(1, 8)]
    v = _verdict(pd.DataFrame(rows))
    assert v.verdict == "ambiguous"
    assert v.ambiguity_note is not None
