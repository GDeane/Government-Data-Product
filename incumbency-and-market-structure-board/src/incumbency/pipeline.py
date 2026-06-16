"""Orchestration: raw -> clean/normalize -> entity-resolve -> canonical awards -> markets.

The same path runs for synthetic fixtures and live CKAN data (D0.1); only the source of the
raw combined table differs. Output is two DataFrames — `awards` (canonical per-award) and
`markets` (aggregated metrics + verdict) — plus the entity-resolution results for inspection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

from . import clean, normalize, signals
from .config import BID_MANDATE_DATE
from .entities import Adjudicator, ResolutionResult, resolve_entities
from .fixtures import DEPARTMENT_CROSSWALK, VENDOR_CROSSWALK


@dataclass
class PipelineResult:
    awards: pd.DataFrame
    markets: pd.DataFrame
    vendor_resolution: ResolutionResult
    buyer_resolution: ResolutionResult


def build_canonical_awards(
    raw: pd.DataFrame,
    vendor_crosswalk: Optional[dict] = None,
    dept_crosswalk: Optional[dict] = None,
    adjudicator: Optional[Adjudicator] = None,
) -> tuple[pd.DataFrame, ResolutionResult, ResolutionResult]:
    """Transform a raw combined table (CanadaBuys/PD shape) into the canonical award table.

    Cleaning, currency, dates and amendment classification are deterministic (Milestone 2);
    procedure/instrument are rule-based enums (D2.4); vendor & buyer names are resolved to
    canonical entities (Milestone 3)."""
    vendor_crosswalk = vendor_crosswalk if vendor_crosswalk is not None else VENDOR_CROSSWALK
    dept_crosswalk = dept_crosswalk if dept_crosswalk is not None else DEPARTMENT_CROSSWALK

    vendor_res = resolve_entities(raw["vendorName"].tolist(),
                                  crosswalk=vendor_crosswalk, adjudicator=adjudicator)
    buyer_res = resolve_entities(raw["buyerName"].tolist(),
                                 crosswalk=dept_crosswalk, adjudicator=adjudicator)

    out_rows = []
    for _, r in raw.iterrows():
        vendor_raw = r["vendorName"]
        buyer_raw = r["buyerName"]
        amendment_number = r.get("amendmentNumber", "000")
        amendment_type = r.get("amendmentType", "")

        commodity, commodity_type = normalize.commodity_key(r.get("unspsc"), r.get("gsin"))
        award_value = clean.parse_value(r.get("contractValue"))
        amend_delta = clean.parse_value(r.get("amendmentValue"))
        pd_value = clean.parse_value(r.get("pdValue"))
        currency = clean.normalize_currency(r.get("currency"))
        num_bids = clean.parse_bids(r.get("numberOfBids"))
        award_date = clean.parse_date(r.get("contractAwardDate"))
        post_mandate = bool(award_date and award_date >= BID_MANDATE_DATE)

        flags = []
        if currency != "CAD":
            flags.append("non_cad")
        if clean.detect_value_conflict(award_value, pd_value):
            flags.append("value_conflict")
        if not normalize.procedure_is_recognised(r.get("solicitationProcedure")):
            flags.append("procedure_unknown")
        if vendor_raw in vendor_res.low_confidence:
            flags.append("low_merge_confidence")

        out_rows.append({
            "solicitation_number": r.get("solicitationNumber"),
            "vendor_raw": vendor_raw,
            "vendor_canonical": vendor_res.canonical_of.get(
                (vendor_raw or "").strip(), vendor_raw),
            "vendor_cluster_id": vendor_res.cluster_of.get((vendor_raw or "").strip()),
            "buyer_raw": buyer_raw,
            "buyer_canonical": buyer_res.canonical_of.get(
                (buyer_raw or "").strip(), buyer_raw),
            "gsin": normalize.normalize_gsin(r.get("gsin")),
            "unspsc": normalize.normalize_unspsc(r.get("unspsc")),
            "commodity": commodity,
            "commodity_type": commodity_type,
            "procedure_class": normalize.classify_procedure(r.get("solicitationProcedure")),
            "instrument_class": normalize.classify_instrument(r.get("instrumentType")),
            "award_value_cad": award_value,
            "original_value_cad": clean.parse_value(r.get("originalValue")),
            "amendment_total_cad": amend_delta,
            "num_bids": num_bids,
            "has_bid_count": num_bids is not None,
            "post_mandate": post_mandate,
            "award_date": award_date,
            "is_amendment": clean.is_amendment(amendment_number),
            "is_admin_amendment": clean.is_admin_amendment(
                amendment_type, amendment_number, amend_delta),
            "source": r.get("source", ""),
            "source_record_id": r.get("sourceRecordId", r.get("solicitationNumber")),
            "confidence_flags": flags,
        })

    awards = pd.DataFrame(out_rows)
    return awards, vendor_res, buyer_res


def run_pipeline(raw: pd.DataFrame, today: Optional[date] = None,
                 adjudicator: Optional[Adjudicator] = None) -> PipelineResult:
    awards, vendor_res, buyer_res = build_canonical_awards(raw, adjudicator=adjudicator)
    markets = signals.compute_markets(awards, resolution=vendor_res, today=today)
    return PipelineResult(awards, markets, vendor_res, buyer_res)


def build_rfps(raw_rfps: pd.DataFrame, dept_crosswalk: Optional[dict] = None) -> pd.DataFrame:
    """Map raw open-tender-notice rows to the canonical RFP table used by the 'who's my
    competition' link. Buyer names are canonicalized with the same department crosswalk used
    for awards, so a posted RFP's buyer matches the historical market's `buyer_canonical`."""
    dept_crosswalk = dept_crosswalk if dept_crosswalk is not None else DEPARTMENT_CROSSWALK
    if raw_rfps is None or raw_rfps.empty:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["solicitation_number"] = raw_rfps.get("solicitationNumber")
    out["title"] = raw_rfps.get("title")
    out["gsin"] = raw_rfps.get("gsin").map(normalize.normalize_gsin)
    unspsc_col = (raw_rfps.get("unspsc") if "unspsc" in raw_rfps.columns
                  else pd.Series([None] * len(raw_rfps)))
    out["unspsc"] = unspsc_col.map(normalize.normalize_unspsc)
    commodity = [normalize.commodity_key(u, g)
                 for u, g in zip(unspsc_col, raw_rfps.get("gsin"))]
    out["commodity"] = [c for c, _ in commodity]
    out["commodity_type"] = [t for _, t in commodity]
    buyer_raw = raw_rfps.get("buyerName").fillna("")
    out["buyer_raw"] = buyer_raw
    out["buyer_canonical"] = buyer_raw.map(lambda b: dept_crosswalk.get(str(b).strip(),
                                                                        str(b).strip()))
    out["closing_date"] = raw_rfps.get("tenderClosingDate").map(clean.parse_date)
    out["category"] = raw_rfps.get("procurementCategory")
    out["procurement_method"] = raw_rfps.get("procurementMethod")
    out["source"] = "open_tenders"
    return out
