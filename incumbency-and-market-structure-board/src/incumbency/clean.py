"""Cleaning helpers: value parsing, date normalization, currency handling, amendment
classification, and value-conflict detection (Milestone 2 / spec §2.3).

All functions are pure and unit-tested. They operate on scalars/rows so the same logic is
reused for synthetic fixtures and live CKAN data."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

# --- Value parsing --------------------------------------------------------------------
_VALUE_CLEAN_RE = re.compile(r"[^0-9.\-]")


def parse_value(raw) -> Optional[float]:
    """Parse a money value that may arrive as '$1,234.50', '1234.5', '(500)' or ''.

    Returns None for unparseable/blank. Parentheses are treated as negative (accounting
    style), which surfaces credit/reversal amendment rows rather than hiding them."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = _VALUE_CLEAN_RE.sub("", s)
    if s in ("", "-", ".", "-."):
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if negative else val


# --- Bid counts (D7) ------------------------------------------------------------------
def parse_bids(raw) -> Optional[int]:
    """Parse a disclosed number_of_bids. Returns a non-negative int, or None when not
    disclosed/unparseable. The field only became mandatory on 2023-06-30, so None is common
    and expected for older awards (the caller distinguishes pre- vs post-mandate)."""
    if raw is None:
        return None
    if isinstance(raw, bool):  # guard: bool is an int subclass
        return None
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and (raw != raw):  # NaN
            return None
        return int(raw) if raw >= 0 else None
    s = str(raw).strip()
    if not s:
        return None
    m = re.match(r"-?\d+", s)
    if not m:
        return None
    val = int(m.group(0))
    return val if val >= 0 else None


# --- Currency (D2.2) ------------------------------------------------------------------
def normalize_currency(raw) -> str:
    """Currency null/blank => 'CAD' per CanadaBuys docs. Returns an uppercase ISO-ish code.

    Non-CAD rows are *not* converted (no FX table in scope); the caller flags them so the
    value is never silently treated as comparable CAD."""
    if raw is None:
        return "CAD"
    s = str(raw).strip().upper()
    return s if s else "CAD"


# --- Dates (D4.2: ordering key for turnover, so this must be right) -------------------
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S",
                 "%Y-%m-%d %H:%M:%S", "%b %d, %Y", "%B %d, %Y")


def parse_date(raw) -> Optional[date]:
    """Parse a date from the several formats seen across CanadaBuys/PD. Returns a date or
    None. Turnover ordering depends on this, so unparseable dates return None (the award is
    excluded from turnover ordering) rather than a guessed value."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Last resort: leading ISO date inside a longer string.
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


# --- Amendments (D2.3) ----------------------------------------------------------------
# Amendment-type strings that indicate a *purely administrative* change (no new market
# event) and so must be excluded from award counts / turnover. Conservative keyword set.
_ADMIN_AMENDMENT_KEYWORDS = (
    "administrative", "admin", "no change to value", "no financial", "correction",
    "extension of time", "time extension", "address change", "name change only",
)


def is_admin_amendment(amendment_type, amendment_number=None,
                       value_delta: Optional[float] = None) -> bool:
    """True if an amendment row is purely administrative (D2.3).

    Primary signal is the `amendmentType` field (present after the 2026 restructuring). If
    that field is absent (D1.3 graceful degradation), fall back to: an amendment with zero
    value change is treated as administrative."""
    text = "" if amendment_type is None else str(amendment_type).strip().lower()
    if text:
        return any(k in text for k in _ADMIN_AMENDMENT_KEYWORDS)
    # Fallback heuristic when amendmentType is unavailable.
    if amendment_number not in (None, "", "000", 0) and value_delta is not None:
        return abs(value_delta) < 1e-9
    return False


def is_amendment(amendment_number) -> bool:
    """True if this row is an amendment (amendment number present and not the base '000')."""
    if amendment_number in (None, ""):
        return False
    s = str(amendment_number).strip()
    return s not in ("", "000", "0")


# --- Value conflicts (D2.5) -----------------------------------------------------------
def detect_value_conflict(award_value: Optional[float], pd_value: Optional[float],
                          rel_tol: float = 0.01) -> bool:
    """True if CanadaBuys award value and proactive-disclosure value disagree beyond
    tolerance for the same solicitation. Both are kept; this only sets a flag (D2.5)."""
    if award_value is None or pd_value is None:
        return False
    if award_value == 0 and pd_value == 0:
        return False
    denom = max(abs(award_value), abs(pd_value), 1.0)
    return abs(award_value - pd_value) / denom > rel_tol
