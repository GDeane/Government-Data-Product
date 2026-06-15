"""Deterministic synthetic dataset (D0.1).

Produces *raw*, deliberately messy data in roughly CanadaBuys/proactive-disclosure shape so
it flows through the exact same clean -> normalize -> entity-resolve -> signals path as live
data. It is engineered to contain, with hand-checkable numbers, one market for each verdict
and — crucially — the two cases the disclosed bid count (D7) now disambiguates:

  * enterable (dynamic)       — D302A / PSPC: concentrated but turns over, open, no lock-in.
  * walled (lock-in)          — R019C / DND:  one vendor via standing offers / call-ups.
  * ambiguous (no coverage)   — N7030 / SSC:  concentrated + open + zero turnover, all
                                pre-2023-06-30 so NO bid coverage -> stays ambiguous.
  * enterable (thin field)    — J5005 / SSC:  concentrated + open + low turnover, but
                                post-mandate awards are mostly SINGLE-bid -> thin field.
  * walled (strong incumbent) — V1124 / CRA:  concentrated + open + low turnover, but
                                post-mandate awards draw MANY bids -> a strong incumbent.
  * insufficient_data         — L0998 / CRA:  too few awards.
  * enterable (fragmented)    — B0079 / ESDC: many vendors, no entrenched incumbent.

Messiness exercised: legal-suffix / regional / FR-EN / case variants of one vendor; an M&A
rename needing the crosswalk; a near-duplicate pair that must land in needs_review; admin &
financial amendments; a value conflict; a null currency; an unparseable date; bid counts
present only for post-2023-06-30 awards."""

from __future__ import annotations

from itertools import cycle

import pandas as pd

# Department canonicalization crosswalk (D3.1). Variants -> canonical label.
DEPARTMENT_CROSSWALK = {
    "Public Works and Government Services Canada": "Public Services and Procurement Canada",
    "PSPC": "Public Services and Procurement Canada",
    "TPSGC": "Public Services and Procurement Canada",
    "DND": "Department of National Defence",
    "MDN": "Department of National Defence",
    "SSC": "Shared Services Canada",
    "CRA": "Canada Revenue Agency",
    "ESDC": "Employment and Social Development Canada",
}

# Vendor M&A / acronym crosswalk for top-N vendors (D3.1). These would NOT fuzzy-match.
VENDOR_CROSSWALK = {
    "Globex Corp": "Globex Corporation",
    "Globex Defence Systems": "Globex Corporation",  # acquired subsidiary, post-M&A
}

# Acme appears under many raw variants that must all collapse to one entity (D3) — this is
# what makes the enterable market's concentration & turnover correct rather than phantom.
_ACME_VARIANTS = cycle([
    "Acme Inc.", "Acme Inc", "ACME INCORPORATED", "Acme Ltd.", "Acme Inc. (Ottawa)",
])


def _row(sol, vendor, buyer, gsin, procedure, instrument, value, award_date,
         *, unspsc="", currency=None, amendment_number="000", amendment_type="",
         original_value=None, pd_value=None, num_bids=None,
         source="award_notices", rec=None):
    return {
        "solicitationNumber": sol,
        "vendorName": vendor,
        "buyerName": buyer,
        "gsin": gsin,
        "unspsc": unspsc,
        "solicitationProcedure": procedure,
        "instrumentType": instrument,
        "contractValue": value,
        "originalValue": original_value if original_value is not None else value,
        "amendmentValue": "" if amendment_number in ("000", "0", "") else value,
        "currency": currency,
        "contractAwardDate": award_date,
        "amendmentNumber": amendment_number,
        "amendmentType": amendment_type,
        "pdValue": pd_value,
        "numberOfBids": num_bids,
        "source": source,
        "sourceRecordId": rec or sol,
    }


def generate_raw_awards() -> pd.DataFrame:
    rows = []
    n = 0

    def sol():
        nonlocal n
        n += 1
        return f"SOL-{n:04d}"

    # --- ENTERABLE (dynamic): D302A / PSPC. Concentrated (~66% Acme) but dynamic & open. -
    # (vendor, value, date, bids) — bids only disclosed for post-2023-06-30 awards.
    enterable = [
        ("Globex Corp", 300_000, "2019-03-04", None),     # M&A crosswalk variant
        ("Globex Corporation", 250_000, "2020-02-11", None),
        (next(_ACME_VARIANTS), 200_000, "2020-06-18", None),
        (next(_ACME_VARIANTS), 400_000, "2021-01-22", None),  # Acme overtakes -> lead change
        (next(_ACME_VARIANTS), 300_000, "2021-09-30", None),
        (next(_ACME_VARIANTS), 350_000, "2022-03-15", None),
        ("Cedar Analytics Ltd", 150_000, "2022-08-09", None),
        (next(_ACME_VARIANTS), 300_000, "2023-02-27", None),
        ("Acme Inc.", 250_000, "2023-10-05", 3),
        ("Cedar Analytics Ltd", 200_000, "2024-01-19", 4),
        ("Birchwood Advisory Inc", 180_000, "2024-05-02", 2),  # recent new entrant 2024
        ("ACME INCORPORATED", 300_000, "2024-09-14", 5),
        ("Acme Ltd.", 250_000, "2025-02-08", 3),
        ("Cedar Analytics Ltd", 150_000, "2025-06-21", 4),
    ]
    for vendor, value, d, bids in enterable:
        rows.append(_row(sol(), vendor, "Public Services and Procurement Canada", "D302A",
                         "Open Bidding", "Contract", value, d, unspsc="80101500", num_bids=bids))
    rows.append(_row(sol(), "Acme Inc", "PSPC", "D302A", "Competitive - Open", "Contract",
                     220_000, "2025-03-30", unspsc="80101500", num_bids=2))
    # A financial amendment (counts toward value, not award events) + an admin one.
    rows.append(_row("SOL-0012", "ACME INCORPORATED", "Public Services and Procurement Canada",
                     "D302A", "Open Bidding", "Contract", 50_000, "2025-01-10",
                     amendment_number="001", amendment_type="Increase to contract value"))
    rows.append(_row("SOL-0012", "ACME INCORPORATED", "Public Services and Procurement Canada",
                     "D302A", "Open Bidding", "Contract", 50_000, "2025-04-12",
                     amendment_number="002", amendment_type="Administrative correction"))
    # A value conflict: proactive disclosure reports a different number for one solicitation.
    rows.append(_row(sol(), "Acme Inc.", "Public Services and Procurement Canada", "D302A",
                     "Open Bidding", "Contract", 275_000, "2025-05-05", unspsc="80101500",
                     pd_value=412_000, num_bids=3, source="proactive_disclosure"))

    # --- WALLED (lock-in): R019C / DND. One vendor, standing offers + call-ups. ----------
    walled = [
        ("Globex Corporation", "Standing Offer", 500_000, "2019-04-01", None),
        ("Globex Corporation", "Call-up against standing offer", 300_000, "2020-04-01", None),
        ("Globex Defence Systems", "Call-up against standing offer", 320_000, "2021-04-01", None),
        ("Globex Corporation", "Standing Offer", 480_000, "2022-04-01", None),
        ("Globex Corporation", "Call-up against standing offer", 310_000, "2023-04-01", None),
        ("Globex Corporation", "Call-up against standing offer", 290_000, "2024-04-01", 1),
        ("Globex Corporation", "Standing Offer", 460_000, "2025-04-01", 1),
        ("Globex Corporation", "Call-up against standing offer", 300_000, "2025-09-01", 1),
    ]
    for vendor, instrument, value, d, bids in walled:
        rows.append(_row(sol(), vendor, "Department of National Defence", "R019C",
                         "Selective Tendering", instrument, value, d, unspsc="81111800",
                         num_bids=bids))

    # --- AMBIGUOUS (no coverage): N7030 / SSC. Concentrated + open + zero turnover, all ---
    # pre-mandate so there is NO bid coverage -> the verdict stays honestly ambiguous.
    ambiguous = [
        ("Initech LLC", 220_000, "2016-07-01"),
        ("Initech LLC", 240_000, "2017-07-01"),
        ("Initech LLC", 210_000, "2018-07-01"),
        ("Initech LLC", 260_000, "2019-07-01"),
        ("Initech LLC", 230_000, "2020-07-01"),
        ("Initech LLC", 250_000, "2021-07-01"),
        ("Initech LLC", 245_000, "2022-07-01"),
    ]
    for vendor, value, d in ambiguous:
        rows.append(_row(sol(), vendor, "Shared Services Canada", "N7030",
                         "Open Bidding", "Contract", value, d, unspsc="81112200",
                         currency=("CAD" if d != "2018-07-01" else None)))  # one null currency

    # --- ENTERABLE (thin field): J5005 / SSC. Concentrated + open + low turnover, but the -
    # incumbent wins largely UNOPPOSED post-mandate -> a thin field you could enter (D7).
    thin_field = [
        ("Soliton Systems Inc", 180_000, "2021-05-01", None),
        ("Soliton Systems Inc", 175_000, "2022-05-01", None),
        ("Soliton Systems Inc", 190_000, "2023-09-01", 1),
        ("Soliton Systems Inc", 185_000, "2024-02-01", 1),
        ("Soliton Systems Inc", 200_000, "2024-08-01", 2),
        ("Soliton Systems Inc", 195_000, "2025-01-01", 1),
        ("Soliton Systems Inc", 188_000, "2025-07-01", 1),
    ]
    for vendor, value, d, bids in thin_field:
        rows.append(_row(sol(), vendor, "Shared Services Canada", "J5005",
                         "Open Bidding", "Contract", value, d, unspsc="80111620", num_bids=bids))

    # --- WALLED (strong incumbent): V1124 / CRA. Concentrated + open + low turnover, but --
    # the incumbent repeatedly BEATS MANY RIVALS post-mandate -> a genuinely strong target.
    strong_incumbent = [
        ("Hexagon Advisory Inc", 210_000, "2021-06-01", None),
        ("Hexagon Advisory Inc", 220_000, "2022-06-01", None),
        ("Hexagon Advisory Inc", 230_000, "2023-09-15", 6),
        ("Hexagon Advisory Inc", 215_000, "2024-03-15", 8),
        ("Hexagon Advisory Inc", 240_000, "2024-09-15", 5),
        ("Hexagon Advisory Inc", 225_000, "2025-03-15", 7),
        ("Hexagon Advisory Inc", 235_000, "2025-09-15", 9),
    ]
    for vendor, value, d, bids in strong_incumbent:
        rows.append(_row(sol(), vendor, "Canada Revenue Agency", "V1124",
                         "Open Bidding", "Contract", value, d, unspsc="80101600", num_bids=bids))

    # --- INSUFFICIENT DATA: L0998 / CRA. Too few awards. --------------------------------
    insufficient = [
        ("Umbrella Data Corp", 90_000, "2023-05-01"),
        ("Umbrella Data Corp", 95_000, "2024-05-01"),
        ("Wayne Systems Inc", 88_000, "bad-date"),  # unparseable date -> excluded from order
    ]
    for vendor, value, d in insufficient:
        rows.append(_row(sol(), vendor, "Canada Revenue Agency", "L0998",
                         "Open Bidding", "Contract", value, d, unspsc="81112500"))

    # --- ENTERABLE (FRAGMENTED): B0079 / ESDC. Many vendors, no incumbent. --------------
    # Includes a near-duplicate pair (Riverbend Analytics Services / ...Solutions) that lands
    # in the adjudication band, stays unmerged (conservative), and surfaces as "possible same
    # vendor" so the user can judge whether the turnover is real or phantom (D3.3).
    fragmented = [
        ("Riverbend Analytics Services", 120_000, "2019-02-01", None),
        ("Stark Consulting Ltd", 110_000, "2019-08-01", None),
        ("Wayne Systems Inc", 130_000, "2020-03-01", None),
        ("Pied Piper Inc", 100_000, "2020-11-01", None),
        ("Hooli Services Ltd", 140_000, "2021-05-01", None),
        ("Riverbend Analytics Solutions", 115_000, "2021-12-01", None),
        ("Stark Consulting Ltd", 105_000, "2022-06-01", None),
        ("Wayne Systems Inc", 125_000, "2023-01-01", None),
        ("Pied Piper Inc", 135_000, "2023-09-01", 4),
        ("Hooli Services Ltd", 118_000, "2024-04-01", 3),
        ("Stark Consulting Ltd", 122_000, "2025-02-01", 5),
        ("Wayne Systems Inc", 128_000, "2025-08-01", 6),
    ]
    for vendor, value, d, bids in fragmented:
        rows.append(_row(sol(), vendor, "Employment and Social Development Canada", "B0079",
                         "Open Bidding", "Contract", value, d, unspsc="80111600", num_bids=bids))

    return pd.DataFrame(rows)
