"""Market-structure signals (Milestone 4 / FR4-FR7).

Every number here is deterministic and re-derivable from the per-award table (NFR3). The
central rule (D4.4) is encoded in `decide_verdict`: high concentration + open procedure +
near-zero turnover yields **ambiguous**, never **enterable** — the directional ambiguity
the spec insists we surface rather than resolve."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

from .config import THRESHOLDS, Thresholds
from .schema import LOCKIN_INSTRUMENTS, NON_OPEN_PROCEDURES


# --- Concentration (D4.1) -------------------------------------------------------------
def value_by_vendor(df: pd.DataFrame) -> dict:
    """Total non-admin award value (CAD) per canonical vendor."""
    sub = df[~df["is_admin_amendment"].fillna(False)]
    out = (sub.groupby("vendor_canonical")["award_value_cad"]
           .sum(min_count=1).dropna().to_dict())
    return {k: v for k, v in out.items() if v and v > 0}


def top1_share(vbv: dict) -> float:
    total = sum(vbv.values())
    if total <= 0:
        return 0.0
    return max(vbv.values()) / total


def hhi(vbv: dict) -> float:
    """Herfindahl-Hirschman Index on award-value shares, 0..1 (secondary view, D4.1)."""
    total = sum(vbv.values())
    if total <= 0:
        return 0.0
    return sum((v / total) ** 2 for v in vbv.values())


def top1_vendor(vbv: dict) -> Optional[str]:
    return max(vbv, key=vbv.get) if vbv else None


def count_by_vendor(df: pd.DataFrame) -> dict:
    """Number of *award events* (base awards, excluding amendments/admin) won per canonical
    vendor — i.e. how many contracts each competitor has won in this market."""
    events = df[~df["is_amendment"].fillna(False) & ~df["is_admin_amendment"].fillna(False)]
    return events.groupby("vendor_canonical").size().to_dict()


def topk_shares(vbv: dict, k: int = 3) -> list:
    """Top-k vendors by award-value share, as [(vendor, share), ...] (D4.1 → competition)."""
    total = sum(vbv.values())
    if total <= 0:
        return []
    ranked = sorted(vbv.items(), key=lambda kv: kv[1], reverse=True)
    return [(v, val / total) for v, val in ranked[:k]]


def vendor_share_table(df: pd.DataFrame) -> list:
    """Per-vendor market-share rows for the 'who's my competition' pie, sorted by value
    share descending. Each row carries BOTH bases: dollar share and award-count share."""
    vbv = value_by_vendor(df)
    cbv = count_by_vendor(df)
    total_v = sum(vbv.values())
    total_c = sum(cbv.values()) or 0
    rows = []
    for vendor, value in sorted(vbv.items(), key=lambda kv: kv[1], reverse=True):
        awards = int(cbv.get(vendor, 0))
        rows.append({
            "vendor": vendor,
            "value": round(float(value), 2),
            "value_share": round(value / total_v, 4) if total_v else 0.0,
            "awards": awards,
            "count_share": round(awards / total_c, 4) if total_c else 0.0,
        })
    return rows


# --- Turnover / dynamism (D4.2) -------------------------------------------------------
@dataclass
class TurnoverMetrics:
    distinct_winners: int
    lead_changes: int
    last_new_entrant_date: Optional[date]
    years_since_new_entrant: Optional[float]


def turnover_metrics(df: pd.DataFrame, today: Optional[date] = None) -> TurnoverMetrics:
    """Compute dynamism over *award events* (base awards, excluding admin amendments),
    ordered by award_date.

    - distinct_winners: number of distinct canonical vendors that have won.
    - lead_changes: number of times the cumulative-value leader changed, walking awards in
      date order (the core dynamism signal).
    - last_new_entrant_date: most recent date a vendor won in this market for the *first*
      time, excluding the original incumbent (None if only one vendor ever won).
    """
    today = today or date.today()
    events = df[~df["is_amendment"].fillna(False) & ~df["is_admin_amendment"].fillna(False)]
    events = events.dropna(subset=["award_date"]).sort_values("award_date")

    distinct = sorted(set(df.loc[~df["is_admin_amendment"].fillna(False), "vendor_canonical"]
                          .dropna()))
    distinct_winners = len(distinct)

    cumulative: dict = defaultdict(float)
    current_leader = None
    lead_changes = 0
    first_win: dict = {}

    for _, row in events.iterrows():
        v = row["vendor_canonical"]
        if v is None:
            continue
        if v not in first_win and row["award_date"] is not None:
            first_win[v] = row["award_date"]
        val = row["award_value_cad"]
        cumulative[v] += float(val) if pd.notna(val) else 0.0
        leader = max(cumulative, key=cumulative.get)
        if current_leader is None:
            current_leader = leader
        elif leader != current_leader:
            lead_changes += 1
            current_leader = leader

    last_new_entrant_date = None
    years_since = None
    if len(first_win) >= 2:
        # The earliest first-win is the original incumbent; later ones are new entrants.
        ordered = sorted(first_win.values())
        last_new_entrant_date = ordered[-1]
        years_since = (today - last_new_entrant_date).days / 365.25

    return TurnoverMetrics(distinct_winners, lead_changes, last_new_entrant_date, years_since)


# --- Bid-count signal (D7) — measured competition evidence ----------------------------
@dataclass
class BidMetrics:
    post_mandate_awards: int     # award events on/after the mandate date
    covered_awards: int          # post-mandate award events WITH a disclosed bid count
    bid_coverage: float          # covered / post_mandate (0..1)
    single_bid_rate: Optional[float]  # share of covered awards with exactly 1 bid
    median_bids: Optional[float]
    signal: str                  # 'strong' | 'weak' | 'none'


def bid_metrics(df: pd.DataFrame, th: Thresholds = THRESHOLDS) -> BidMetrics:
    """Measured single-bid signal from disclosed `number_of_bids` (D7).

    Computed over *award events* (base awards, no admin amendments) on/after the 2023-06-30
    mandate date, since that is the only period for which the field is mandatory and
    coverage is meaningful. The signal is 'strong' only when enough post-mandate awards
    actually carry a disclosed count — otherwise we do not let it move a verdict."""
    events = df[~df["is_amendment"].fillna(False) & ~df["is_admin_amendment"].fillna(False)]
    post = events[events["post_mandate"].fillna(False)]
    post_n = int(post.shape[0])
    covered = post[post["has_bid_count"].fillna(False)]
    covered_n = int(covered.shape[0])

    coverage = (covered_n / post_n) if post_n else 0.0
    if covered_n == 0:
        return BidMetrics(post_n, 0, round(coverage, 4), None, None, "none")

    bids = covered["num_bids"].dropna().astype(float)
    single_rate = float((bids == 1).mean())
    median = float(bids.median())
    signal = "strong" if covered_n >= th.min_covered_awards_for_bids else "weak"
    return BidMetrics(post_n, covered_n, round(coverage, 4),
                      round(single_rate, 4), median, signal)


# --- Procedure / instrument mix -------------------------------------------------------
def _value_share_by(df: pd.DataFrame, col: str) -> dict:
    sub = df[~df["is_admin_amendment"].fillna(False)]
    total = sub["award_value_cad"].sum(min_count=1)
    if not total or total <= 0:
        return {}
    grp = sub.groupby(col)["award_value_cad"].sum(min_count=1).dropna()
    return {k: v / total for k, v in grp.items()}


def procedure_mix(df: pd.DataFrame) -> dict:
    return _value_share_by(df, "procedure_class")


def instrument_mix(df: pd.DataFrame) -> dict:
    return _value_share_by(df, "instrument_class")


def open_share(pmix: dict) -> float:
    return pmix.get("open_competitive", 0.0)


def nonopen_share(pmix: dict) -> float:
    return sum(pmix.get(p, 0.0) for p in NON_OPEN_PROCEDURES)


def lockin_share(imix: dict) -> float:
    return sum(imix.get(i, 0.0) for i in LOCKIN_INSTRUMENTS)


# --- Contestability score (D4.3) ------------------------------------------------------
def turnover_norm(tm: TurnoverMetrics, n_awards: int, th: Thresholds) -> float:
    """Normalize turnover to 0..1 as the mean of three legible sub-signals. Returns 0.0
    when turnover is untrusted (too few awards) — you cannot read dynamism off a handful of
    awards (D4.2)."""
    if n_awards < th.min_awards_for_turnover:
        return 0.0
    distinct_sig = min(max(tm.distinct_winners - 1, 0), 3) / 3.0
    change_sig = min(tm.lead_changes, 2) / 2.0
    if tm.years_since_new_entrant is None:
        recency_sig = 0.0
    else:
        span = th.new_entrant_recency_years * 3.0
        recency_sig = max(0.0, min(1.0, 1.0 - tm.years_since_new_entrant / span))
    return (distinct_sig + change_sig + recency_sig) / 3.0


def contestability_score(open_sh: float, lockin_sh: float, tnorm: float,
                         th: Thresholds = THRESHOLDS) -> float:
    """Transparent 0..100 blend of openness, absence of lock-in, and turnover (D4.3).

    Deliberately does *not* reward low concentration into a 'beatable' label — it ranks
    shortlisted concentrated markets by how enterable they look."""
    raw = (th.w_openness * open_sh
           + th.w_no_lockin * (1.0 - lockin_sh)
           + th.w_turnover * tnorm)
    return round(100.0 * raw, 1)


# --- Verdict (D4.4) — the central rule ------------------------------------------------
@dataclass
class Verdict:
    verdict: str
    reason: str
    confounders: list
    ambiguity_note: Optional[str]
    confidence: str
    competition_note: Optional[str] = None


def format_competition_note(bm: "BidMetrics") -> Optional[str]:
    """Human-readable summary of the measured bid-count signal (D7), shown front and center.
    Always labels coverage and the mandate caveat; returns None when there is no coverage."""
    if bm.signal == "none" or bm.single_bid_rate is None:
        if bm.post_mandate_awards == 0:
            return ("No post-2023-06-30 awards — bid counts only became mandatory then, so "
                    "no measured competition signal; OPO prior applies.")
        return (f"{bm.post_mandate_awards} post-mandate award(s) but none disclose a bid "
                f"count — measured competition signal unavailable; OPO prior applies.")
    strength = "" if bm.signal == "strong" else " (thin coverage — treat with caution)"
    return (f"{bm.single_bid_rate:.0%} of {bm.covered_awards} post-mandate award(s) with a "
            f"disclosed bid count drew a SINGLE bid (median {bm.median_bids:g} bids){strength}.")


def _confidence(n_awards: int, th: Thresholds) -> str:
    if n_awards >= 2 * th.min_awards_for_turnover:
        return "high"
    if n_awards >= th.min_awards_for_turnover:
        return "medium"
    return "low"


def decide_verdict(*, n_awards: int, top1: float, pmix: dict, imix: dict,
                   tm: TurnoverMetrics, bm: BidMetrics,
                   th: Thresholds = THRESHOLDS) -> Verdict:
    open_sh = open_share(pmix)
    nonopen_sh = nonopen_share(pmix)
    lockin_sh = lockin_share(imix)
    comp_note = format_competition_note(bm)

    confounders = []
    if lockin_sh > 0:
        confounders.append(f"{lockin_sh:.0%} of value via standing offer / call-up "
                           f"(position locked for a term)")
    if nonopen_sh > 0:
        confounders.append(f"{nonopen_sh:.0%} of value via sole-source / ACAN "
                           f"(justification on record)")
    if tm.distinct_winners <= 1:
        confounders.append("only one supplier ever observed (may be a genuinely thin field)")

    conf = _confidence(n_awards, th)

    if n_awards < th.min_awards:
        return Verdict("insufficient_data",
                       f"only {n_awards} award(s) on record — too few for a verdict",
                       confounders, None, "low", comp_note)

    concentrated = top1 >= th.concentration_high
    locked = lockin_sh >= th.lockin_high
    nonopen = nonopen_sh >= th.nonopen_high
    open_market = open_sh >= th.open_high

    if not concentrated:
        return Verdict(
            "enterable",
            f"no single vendor holds a dominant share (top-1 {top1:.0%}) — "
            f"no entrenched incumbent",
            confounders, None, conf, comp_note)

    # Concentrated -> shortlist candidate. Now decide *why* it is concentrated.
    if locked or nonopen:
        why = "standing-offer / call-up lock-in" if locked else "sole-source / ACAN procedure"
        return Verdict(
            "walled",
            f"one vendor holds {top1:.0%} of award value and the position is held via "
            f"{why} — not structurally enterable",
            confounders, None, conf, comp_note)

    turnover_trusted = n_awards >= th.min_awards_for_turnover
    has_turnover = (tm.distinct_winners >= th.turnover_min_distinct_winners
                    and tm.lead_changes >= th.turnover_min_lead_changes)

    if open_market and turnover_trusted and has_turnover:
        recent = (f", most recent new entrant {tm.last_new_entrant_date}"
                  if tm.last_new_entrant_date else "")
        return Verdict(
            "enterable",
            f"concentrated (top-1 {top1:.0%}) but dynamic: {tm.distinct_winners} distinct "
            f"winners, {tm.lead_changes} lead change(s){recent}, all under open procedure "
            f"with no lock-in — the incumbent's position is beatable",
            confounders, None, conf, comp_note)

    if open_market:
        # High concentration + open + near-zero turnover: historically THE ambiguous case
        # ("thin field or strong incumbent, can't tell"). The disclosed bid count (D7) is
        # exactly the field that disambiguates it — where coverage is strong.
        bids_resolve = (bm.signal == "strong" and bm.single_bid_rate is not None)
        if bids_resolve and bm.single_bid_rate >= th.single_bid_high:
            return Verdict(
                "enterable",
                f"concentrated (top-1 {top1:.0%}), open, low turnover — but the incumbent "
                f"wins largely UNOPPOSED ({bm.single_bid_rate:.0%} of {bm.covered_awards} "
                f"post-mandate awards drew a single bid). That points to a THIN FIELD, not a "
                f"proven-strong incumbent: a market you could enter by simply showing up",
                confounders, None, conf, comp_note)
        if bids_resolve and bm.single_bid_rate <= th.single_bid_low:
            return Verdict(
                "walled",
                f"concentrated (top-1 {top1:.0%}), open, low turnover — and the incumbent "
                f"repeatedly BEATS REAL RIVALS (only {bm.single_bid_rate:.0%} single-bid, "
                f"median {bm.median_bids:g} bids across {bm.covered_awards} post-mandate "
                f"awards). That points to a genuinely STRONG incumbent — a hard target",
                confounders, None, conf, comp_note)
        # Bids don't resolve it (thin/no coverage, or a mid-range single-bid rate): the
        # spec's honest ambiguous verdict stands.
        if bids_resolve:
            note = ("Concentrated and open with low turnover. Bid counts are mixed "
                    f"({bm.single_bid_rate:.0%} single-bid) — neither clearly a thin field "
                    "nor a strong incumbent, so we do not guess.")
        else:
            note = ("Concentrated under an open procedure with near-zero turnover. The "
                    "disclosed bid count would separate a thin field from a strong "
                    "incumbent, but there is too little post-2023-06-30 coverage here — so "
                    "this stays genuinely ambiguous (OPO prior is the only context).")
        return Verdict(
            "ambiguous",
            f"concentrated (top-1 {top1:.0%}) and open, but turnover is near zero "
            f"({tm.distinct_winners} distinct winner(s), {tm.lead_changes} lead change(s))",
            confounders, note, conf, comp_note)

    # Mixed procedure posture, neither clearly open nor clearly non-open.
    return Verdict(
        "ambiguous",
        f"concentrated (top-1 {top1:.0%}) with a mixed procedure posture "
        f"(open {open_sh:.0%}, non-open {nonopen_sh:.0%}) — verdict not clear-cut",
        confounders,
        "Procedure posture is mixed; we decline a confident enterable/walled call.",
        conf, comp_note)


# --- Aggregation: per (commodity × buyer) market (D5.1) -------------------------------
def compute_markets(awards: pd.DataFrame, resolution=None,
                    th: Thresholds = THRESHOLDS, today: Optional[date] = None) -> pd.DataFrame:
    """Aggregate the canonical per-award table into one row per (gsin × buyer_canonical)
    market with concentration, turnover, score, verdict, confounders, and provenance.

    `resolution` (optional ResolutionResult from entities.py) is used only to attach
    "possible same vendor" notes where unresolved near-duplicates affect a market's winner
    set (D3.3)."""
    today = today or date.today()
    rows = []
    for (commodity, buyer), df in awards.groupby(["commodity", "buyer_canonical"],
                                                 dropna=False):
        # A market needs a real commodity code and buyer; rows with a blank/null commodity
        # are not a commodity market (they would otherwise lump into one giant pseudo-market
        # on live data where commodity coding is missing).
        if (str(commodity).strip().lower() in ("", "nan", "none", "null")
                or str(buyer).strip().lower() in ("", "nan", "none", "null")):
            continue
        commodity_type = next((t for t in df["commodity_type"] if t), "")
        gsin_rep = next((g for g in df["gsin"] if str(g).strip()), "")
        unspsc_rep = next((u for u in df["unspsc"] if str(u).strip()), "")
        non_admin = df[~df["is_admin_amendment"].fillna(False)]
        n_awards = int(non_admin[~non_admin["is_amendment"].fillna(False)].shape[0])

        vbv = value_by_vendor(df)
        t1 = top1_share(vbv)
        topk = topk_shares(vbv, k=3)
        shares = vendor_share_table(df)
        pmix = procedure_mix(df)
        imix = instrument_mix(df)
        tm = turnover_metrics(df, today=today)
        bm = bid_metrics(df, th)
        tnorm = turnover_norm(tm, n_awards, th)
        score = contestability_score(open_share(pmix), lockin_share(imix), tnorm, th)
        v = decide_verdict(n_awards=n_awards, top1=t1, pmix=pmix, imix=imix, tm=tm, bm=bm,
                           th=th)

        psv = []
        if resolution is not None:
            raw_in_market = df["vendor_raw"].dropna().unique().tolist()
            psv = resolution.possible_same_vendor_for(raw_in_market)

        rows.append({
            "commodity": commodity,
            "commodity_type": commodity_type,
            "gsin": gsin_rep,
            "unspsc": unspsc_rep,
            "buyer_canonical": buyer,
            "n_awards": n_awards,
            "top1_vendor": top1_vendor(vbv),
            "top1_share": round(t1, 4),
            "top2_vendor": topk[1][0] if len(topk) > 1 else None,
            "top2_share": round(topk[1][1], 4) if len(topk) > 1 else None,
            "top3_vendor": topk[2][0] if len(topk) > 2 else None,
            "top3_share": round(topk[2][1], 4) if len(topk) > 2 else None,
            "total_value_cad": round(sum(vbv.values()), 2),
            "vendor_shares": shares,
            "hhi": round(hhi(vbv), 4),
            "distinct_winners": tm.distinct_winners,
            "lead_changes": tm.lead_changes,
            "last_new_entrant_date": tm.last_new_entrant_date,
            "years_since_new_entrant": (round(tm.years_since_new_entrant, 2)
                                        if tm.years_since_new_entrant is not None else None),
            "open_share": round(open_share(pmix), 4),
            "nonopen_share": round(nonopen_share(pmix), 4),
            "lockin_share": round(lockin_share(imix), 4),
            "procedure_mix": {k: round(v_, 4) for k, v_ in pmix.items()},
            "instrument_mix": {k: round(v_, 4) for k, v_ in imix.items()},
            "post_mandate_awards": bm.post_mandate_awards,
            "covered_awards": bm.covered_awards,
            "bid_coverage": bm.bid_coverage,
            "single_bid_rate": bm.single_bid_rate,
            "median_bids": bm.median_bids,
            "bid_signal": bm.signal,
            "competition_note": v.competition_note,
            "contestability_score": score,
            "verdict": v.verdict,
            "verdict_reason": v.reason,
            "confounders": v.confounders,
            "ambiguity_note": v.ambiguity_note,
            "possible_same_vendor": psv,
            "solicitation_numbers": sorted(df["solicitation_number"].dropna().unique().tolist()),
            "confidence": v.confidence,
        })

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["contestability_score", "n_awards"], ascending=False) \
                 .reset_index(drop=True)
    return out
