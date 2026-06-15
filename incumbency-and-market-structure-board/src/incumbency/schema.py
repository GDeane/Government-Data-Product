"""Canonical schema definitions and controlled vocabularies.

The per-award table is the single source of truth (D5.1); market-level metrics are always
aggregated from it (NFR3). There is deliberately **no** `num_bids` column anywhere — that
field does not exist in any federal bulk dataset and the pipeline never fabricates one
(D1.4, the headline scope boundary)."""

from __future__ import annotations

# --- Controlled vocabularies (rule-based enums, never AI; D2.4 / FR3) -----------------

PROCEDURE_CLASSES = ("open_competitive", "selective", "ACAN", "sole_source")
INSTRUMENT_CLASSES = ("contract", "standing_offer", "call_up")
VERDICTS = ("enterable", "walled", "ambiguous", "insufficient_data")

# Procedure classes that mean "by construction this was not opened to the field".
NON_OPEN_PROCEDURES = ("ACAN", "sole_source")
# Instrument classes that lock a position in for a term.
LOCKIN_INSTRUMENTS = ("standing_offer", "call_up")

# --- Canonical per-award columns (the target shape from spec §2.3) --------------------
AWARD_COLUMNS = [
    "solicitation_number",   # primary join key (D2.1)
    "vendor_raw",            # name as reported, pre-resolution (kept for provenance)
    "vendor_canonical",      # post entity-resolution (D3)
    "vendor_cluster_id",     # entity-resolution cluster id
    "buyer_raw",
    "buyer_canonical",
    "gsin",
    "unspsc",
    "procedure_class",       # enum PROCEDURE_CLASSES
    "instrument_class",      # enum INSTRUMENT_CLASSES
    "award_value_cad",       # currency-normalized (D2.2)
    "original_value_cad",    # base-award (amendment 000) value (D2.3)
    "amendment_total_cad",
    "num_bids",              # disclosed number_of_bids (D7); None if not disclosed
    "has_bid_count",         # bool: a bid count is present on this row
    "post_mandate",          # bool: award_date >= BID_MANDATE_DATE (2023-06-30)
    "award_date",            # ISO date — ordering key for turnover (D4.2)
    "is_amendment",          # bool: row is an amendment of an earlier award
    "is_admin_amendment",    # bool: purely administrative (excluded from counts; D2.3)
    "source",                # provenance: which dataset (NFR1)
    "source_record_id",
    "confidence_flags",      # list[str]: low_n, value_conflict, low_merge_confidence, non_cad
]

# --- Market-level (commodity × buyer) derived columns ---------------------------------
MARKET_COLUMNS = [
    "gsin",
    "buyer_canonical",
    "n_awards",
    "top1_vendor",
    "top1_share",            # headline concentration (D4.1)
    "hhi",                   # secondary concentration view
    "distinct_winners",      # turnover (D4.2)
    "lead_changes",
    "last_new_entrant_date",
    "years_since_new_entrant",
    "open_share",
    "nonopen_share",
    "lockin_share",
    "procedure_mix",         # dict procedure_class -> value share
    "instrument_mix",        # dict instrument_class -> value share
    # --- Bid-count signal (D7), front-and-center competition evidence ----------------
    "post_mandate_awards",   # award events on/after the 2023-06-30 mandate
    "covered_awards",        # post-mandate award events WITH a disclosed bid count
    "bid_coverage",          # covered_awards / post_mandate_awards (0..1)
    "single_bid_rate",       # share of covered awards with exactly 1 bid (MEASURED)
    "median_bids",           # median disclosed bid count among covered awards
    "bid_signal",            # 'strong' | 'weak' | 'none' — is the rate trustworthy?
    "competition_note",      # human-readable bid-count interpretation
    "contestability_score",  # 0..100 (D4.3)
    "verdict",               # enum VERDICTS (D4.4)
    "verdict_reason",        # human-readable explanation
    "confounders",           # list[str] of benign explanations present
    "ambiguity_note",        # set when verdict == ambiguous (D4.4)
    "possible_same_vendor",  # list of unresolved near-dup pairs affecting winners (D3.3)
    "solicitation_numbers",  # provenance: contributing awards (NFR1)
    "confidence",            # high/medium/low by sample size (FR7)
]
