"""Link currently-posted RFPs to the historical competition for the same kind of work.

A posted RFP is treated as a 'repeat' of historical work when it shares a commodity code with
a historical market. The join is on **UNSPSC *or* GSIN** — UNSPSC is preferred (carried on
~84% of open notices vs ~5% for GSIN), but a GSIN match is accepted as a fallback so a notice
that only carries a GSIN can still be linked. Match precision:

  * exact      — same commodity code *and* same buyer
  * commodity  — same commodity code at any buyer (buyer differs or didn't canonicalize)
  * none       — no commodity code on the notice, or no historical awards for either code

`matched_on` records which code(s) made the link ('unspsc', 'gsin', or 'unspsc+gsin')."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .normalize import normalize_gsin, normalize_unspsc


@dataclass
class RfpMatch:
    precision: str          # 'exact' | 'commodity' | 'none'
    matched_on: str         # 'unspsc' | 'gsin' | 'unspsc+gsin' | ''
    markets: pd.DataFrame   # matching historical market row(s); empty if none


def match_rfp_to_markets(unspsc, gsin, buyer_canonical,
                         markets: pd.DataFrame) -> RfpMatch:
    """Find historical markets for an RFP, joining by UNSPSC or GSIN."""
    u = normalize_unspsc(unspsc)
    g = normalize_gsin(gsin)
    if markets.empty or (not u and not g):
        return RfpMatch("none", "", markets.iloc[0:0])

    parts, codes = [], []
    if u:
        hit = markets[markets["unspsc"].astype(str).str.upper() == u]
        if not hit.empty:
            parts.append(hit)
            codes.append("unspsc")
    if g:
        hit = markets[markets["gsin"].astype(str).str.upper() == g]
        if not hit.empty:
            parts.append(hit)
            codes.append("gsin")
    if not parts:
        return RfpMatch("none", "", markets.iloc[0:0])

    combined = (pd.concat(parts)
                .drop_duplicates(subset=["commodity", "buyer_canonical"]))
    matched_on = "+".join(codes)
    if buyer_canonical:
        exact = combined[combined["buyer_canonical"] == buyer_canonical]
        if not exact.empty:
            return RfpMatch("exact", matched_on, exact)
    return RfpMatch("commodity", matched_on, combined)
