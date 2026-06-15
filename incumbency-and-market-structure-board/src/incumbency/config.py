"""Central configuration: paths, CKAN endpoints, dataset identifiers, and tunable
thresholds. Keeping every magic number here makes the contestability score and verdict
logic fully re-derivable (NFR3) and tunable in one place (spec decision log)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Date `number_of_bids` became a PERMANENT, MANDATORY proactive-disclosure requirement.
# Coverage is judged against awards on/after this date; pre-mandate gaps are expected, not a
# data-quality fault. Provided by the product owner; matches the observed ~2023 fill onset.
BID_MANDATE_DATE = date(2023, 6, 30)

# --- Paths ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
DUCKDB_PATH = DATA_DIR / "market_board.duckdb"

# --- CKAN (open.canada.ca) — read-only action API, no API key (D1.1) ------------------
CKAN_BASE = "https://open.canada.ca/data/en/api/3/action"

# Dataset UUIDs on open.canada.ca. These are the package ids passed to package_show.
# They are recorded here so the live ingest is robust to fiscal-year file renames and the
# 2026 restructuring (we resolve current resource URLs at run time rather than hard-coding
# file links). If a UUID drifts, update it here only. Verified live via CKAN package_search.
CKAN_DATASETS = {
    # CanadaBuys award notices (primary spine).
    "award_notices": "a1acb126-9ce8-40a9-b889-5da2b1dd20cb",
    # CanadaBuys contract history (backbone of the turnover signal).
    "contract_history": "4fe645a1-ffcd-40c1-9385-2c771be956a4",
    # TBS proactive disclosure — "Proactive Publication - Contracts" (DataStore-backed).
    "proactive_disclosure": "d8f85d91-7dec-4fd1-8055-483b77225d8b",
    # CanadaBuys tender notices (originating RFP/ACAN).
    "tender_notices": "6abd20d4-7a1c-4b38-baa2-9525d0bb2fd2",
}

# OPO systemic-review single-bid rates — EXTERNAL PRIOR ONLY (D5.3). Never a per-record
# value. Shown as context for why an "open" label is not proof of a real contest.
OPO_SINGLE_BID_PRIOR = {
    "open_competitive": 0.29,
    "limited": 0.35,
    "source": "OPO systemic review of single-bid competitive procurements",
}


@dataclass(frozen=True)
class Thresholds:
    """Every tunable that affects a verdict or score. Documented in MILESTONES.md §4."""

    # Minimum awards before a market gets any verdict at all (FR7).
    min_awards: int = 5
    # Minimum awards before turnover/dynamism is trusted (D4.2). You cannot read dynamism
    # off a handful of awards.
    min_awards_for_turnover: int = 5

    # Concentration shortlisting band (D4.1). top1 share at/above this = "concentrated"
    # (an entrenched-incumbent shortlist candidate), never "beatable" on its own.
    concentration_high: float = 0.65

    # Lock-in: share of award value under standing_offer/call-up at/above this => walled
    # (D4.4). Also walled if non-open procedure (sole_source/ACAN) dominates.
    lockin_high: float = 0.50
    # Procedure: share of value under open_competitive at/above this = "open market".
    open_high: float = 0.50
    # Procedure: share under sole_source+ACAN at/above this = non-open => walled.
    nonopen_high: float = 0.50

    # Turnover thresholds for the enterable verdict (D4.4).
    turnover_min_distinct_winners: int = 2
    turnover_min_lead_changes: int = 1
    # A "recent" new-entrant win (years). Drives the recency component of the score.
    new_entrant_recency_years: float = 2.0

    # --- Bid-count signal (D7) -------------------------------------------------------
    # Minimum post-mandate awards WITH a disclosed bid count before the single-bid signal
    # is trusted to resolve the thin-field-vs-strong-incumbent ambiguity.
    min_covered_awards_for_bids: int = 3
    # Single-bid rate at/above this => incumbent largely UNOPPOSED => thin field (enterable).
    single_bid_high: float = 0.50
    # Single-bid rate at/below this => incumbent beats REAL rivals => strong incumbent (walled).
    single_bid_low: float = 0.25

    # Contestability score weights (D4.3). Must sum to 1.0; checked at import.
    w_openness: float = 0.34
    w_no_lockin: float = 0.33
    w_turnover: float = 0.33


THRESHOLDS = Thresholds()

# Fail fast if the score weights are mis-edited.
_w_sum = THRESHOLDS.w_openness + THRESHOLDS.w_no_lockin + THRESHOLDS.w_turnover
assert abs(_w_sum - 1.0) < 1e-9, f"contestability score weights must sum to 1.0, got {_w_sum}"


# --- Entity-resolution similarity bands (D3.2) ----------------------------------------
@dataclass(frozen=True)
class EntityResolutionConfig:
    # rapidfuzz token_sort_ratio scale is 0..100.
    auto_merge_at: float = 92.0   # >= this: auto-merge (very high confidence)
    keep_separate_below: float = 78.0  # < this: definitely distinct
    # The [keep_separate_below, auto_merge_at) band goes to the adjudicator (D3.1).
    # Anything the adjudicator is unsure about lands in needs_review (kept separate, D3.2).


ER_CONFIG = EntityResolutionConfig()


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DIR, INTERIM_DIR):
        d.mkdir(parents=True, exist_ok=True)
