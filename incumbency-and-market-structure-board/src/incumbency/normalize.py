"""Rule-based normalization of categorical fields (D2.4 / FR3).

Procedure and instrument classification are deterministic keyword rules over disclosed
categorical fields — never AI. Anything unrecognised maps to a conservative default and is
flagged, so we never silently invent a competitive posture."""

from __future__ import annotations

import re

# Raw procedure strings vary across CanadaBuys / proactive disclosure and across the 2026
# restructuring. We match on normalized keywords. Order matters: most specific first.
_PROCEDURE_RULES = [
    ("ACAN", ("advance contract award", "acan")),
    ("sole_source", ("sole source", "sole-source", "non-competitive", "non competitive",
                      "directed", "exclusive rights", "limited tendering")),
    ("selective", ("selective", "invitational", "pre-qualified", "prequalified",
                   "standing offer refinement", "supply arrangement")),
    ("open_competitive", ("open", "competitive", "electronic bidding", "public",
                          "traditional competitive")),
]

_INSTRUMENT_RULES = [
    ("call_up", ("call-up", "call up", "callup", "against a standing offer",
                 "against sa", "against so")),
    ("standing_offer", ("standing offer", "supply arrangement", "soa", "rfso", "nmso")),
    ("contract", ("contract", "purchase order", "po", "agreement")),
]


# TBS Proactive Disclosure encodes solicitation_procedure as short codes rather than prose.
# Best-effort mapping (live path); documented as approximate since TBS code definitions have
# shifted over time. Exact-code match is tried before keyword matching.
_PD_PROCEDURE_CODES = {
    "OB": "open_competitive",     # Open Bidding
    "TC": "open_competitive",     # Traditional Competitive
    "GC": "open_competitive",     # Government Competitive
    "ST": "selective",            # Selective Tendering
    "AC": "ACAN",                 # Advance Contract Award Notice
    "TN": "sole_source",          # Traditional Non-competitive
    "NC": "sole_source",          # Non-Competitive
    "SS": "sole_source",          # Sole Source
}


def _norm_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def classify_procedure(raw) -> str:
    """Map a raw solicitation-procedure string to a procedure_class enum.

    Default for blank/unrecognised is 'open_competitive' (most federal award volume is
    open), but the caller flags such rows via `procedure_is_recognised` so an assumed-open
    label never silently hardens into an 'enterable' verdict."""
    text = _norm_text(raw)
    if not text:
        return "open_competitive"  # blank: assume open but caller flags as unknown
    # Exact PD short-code match first (live path).
    code = str(raw).strip().upper()
    if code in _PD_PROCEDURE_CODES:
        return _PD_PROCEDURE_CODES[code]
    for cls, keywords in _PROCEDURE_RULES:
        if any(k in text for k in keywords):
            return cls
    return "open_competitive"


def procedure_is_recognised(raw) -> bool:
    """True if the raw value matched an explicit keyword (used to flag unknowns)."""
    text = _norm_text(raw)
    if not text:
        return False
    if str(raw).strip().upper() in _PD_PROCEDURE_CODES:
        return True
    return any(k in text for _, kws in _PROCEDURE_RULES for k in kws)


def classify_instrument(raw) -> str:
    """Map a raw instrumentType string to an instrument_class enum. Blank/unknown ->
    'contract' (the neutral default; degrades gracefully if the 2026 instrumentType field
    is absent, D1.3)."""
    text = _norm_text(raw)
    if not text:
        return "contract"
    for cls, keywords in _INSTRUMENT_RULES:
        if any(k in text for k in keywords):
            return cls
    return "contract"


_NULLISH = {"", "NAN", "NONE", "NULL", "N/A", "NA"}


def normalize_unspsc(raw) -> str:
    """Normalize an 8-digit UNSPSC code to digits only. Handles the float-repr '80101500.0'
    and the null-ish disguises (None / NaN / 'NULL'). Returns '' when absent."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if s.upper() in _NULLISH:
        return ""
    s = re.sub(r"\.0+$", "", s)        # drop a trailing .0 from a float read
    return re.sub(r"\D", "", s)


def commodity_key(unspsc, gsin) -> tuple:
    """The market commodity key: full UNSPSC where present, else GSIN (so sources without
    UNSPSC, e.g. the Proactive-Disclosure spine, still form markets). Returns (code, type)
    where type is 'unspsc' | 'gsin' | '' (absent)."""
    u = normalize_unspsc(unspsc)
    if u:
        return u, "unspsc"
    g = normalize_gsin(gsin)
    if g:
        return g, "gsin"
    return "", ""


def normalize_gsin(raw) -> str:
    """Normalize a GSIN code: uppercase, strip whitespace. GSIN codes are alphanumeric.

    Missing values arrive in several disguises — None, the float NaN (which stringifies to
    'nan'), or literal 'NULL'/'N/A' — and must all collapse to '' so they are never mistaken
    for a real commodity code (which would otherwise fabricate a phantom 'NAN' market)."""
    if raw is None:
        return ""
    s = re.sub(r"\s+", "", str(raw).strip().upper())
    return "" if s in _NULLISH else s
