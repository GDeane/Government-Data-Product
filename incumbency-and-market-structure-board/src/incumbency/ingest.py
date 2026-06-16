"""Live ingestion from the CKAN action API on open.canada.ca — read-only, no API key (D1.1).

The spine for the live path is **TBS Proactive Disclosure ("Contracts over $10,000")**: it is
DataStore-backed (queryable, paginated) and carries every field the board needs in one place
— vendor, buyer (department), commodity code, solicitation procedure, instrument type, value,
date, and (post-2023-06-30) `number_of_bids`. CanadaBuys award/contract-history file datasets
are larger and join awkwardly (reference numbers are inconsistent; D2.1), so they are left as
an enrichment for later. `package_show` is still used to resolve current resource ids so we
are robust to fiscal-year renames and the 2026 restructuring (D1.1).

This path is a bonus over the offline-first synthetic build (D0.1); it is exercised by a
network-gated smoke test, not the core test suite."""

from __future__ import annotations

import io
import re
import time
from typing import Optional

import pandas as pd
import requests

from .config import CKAN_BASE, CKAN_DATASETS

# The DataStore-active "Contracts over $10,000" resource (resolved via package_show, but
# pinned here as the known default to save a round-trip).
_PD_RESOURCE_DEFAULT = "fac950c0-00d5-4ec1-a4d3-9cbebf98a305"

# Proactive-disclosure field -> our raw schema field (consumed by pipeline.build_canonical).
_PD_FIELD_MAP = {
    "reference_number": "solicitationNumber",
    "vendor_name": "vendorName",
    "owner_org_title": "buyerName",
    "commodity_code": "gsin",
    "solicitation_procedure": "solicitationProcedure",
    "instrument_type": "instrumentType",
    "contract_value": "contractValue",
    "original_value": "originalValue",
    "amendment_value": "amendmentValue",
    "contract_date": "contractAwardDate",
    "number_of_bids": "numberOfBids",
}


def _route_commodity_code(raw_code) -> tuple:
    """Split PD's overloaded `commodity_code` into (unspsc, gsin). An 8-digit numeric value is
    a UNSPSC code; anything else (e.g. 'N5830', 'U099AA') is a GSIN. Returns (None, None) for a
    blank/null code. A trailing '.0' from a float read is tolerated before the digit test."""
    if raw_code is None:
        return None, None
    s = str(raw_code).strip()
    if not s or s.lower() == "nan":
        return None, None
    s = re.sub(r"\.0+$", "", s)
    return (s, None) if re.fullmatch(r"\d{8}", s) else (None, s)


def ckan_get(action: str, timeout: int = 60, **params) -> dict:
    """Call a CKAN action endpoint and return its `result`. Raises on API-level failure."""
    resp = requests.get(f"{CKAN_BASE}/{action}", params=params, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success", False):
        raise RuntimeError(f"CKAN action {action} failed: {payload.get('error')}")
    return payload["result"]


# Sibling resources whose names also contain "Contracts over $10,000" but are NOT the main
# table (legacy slice, aggregated totals, nothing-to-report). Must be skipped (D1.2).
_RESOURCE_EXCLUDE_TERMS = ("legacy", "aggregated", "nothing to report", "under")


def find_datastore_resource(package_id: str, name_contains: str,
                            exclude=_RESOURCE_EXCLUDE_TERMS) -> Optional[str]:
    """Return the id of the best DataStore-active resource whose name contains the given text
    (case-insensitive), skipping excluded sibling tables and preferring an exact name match.
    Honors the per-resource DataStore caveat (D1.2): only `datastore_active` resources are
    queryable via datastore_search."""
    pkg = ckan_get("package_show", id=package_id)
    needle = name_contains.lower()
    candidates = []
    for r in pkg.get("resources", []):
        name = (r.get("name") or "").lower()
        if not r.get("datastore_active") or needle not in name:
            continue
        if any(term in name for term in exclude):
            continue
        candidates.append(r)
    if not candidates:
        return None
    exact = next((r for r in candidates if (r.get("name") or "").lower().strip() == needle),
                 None)
    return (exact or candidates[0])["id"]


def datastore_fetch(resource_id: str, max_rows: int = 5000, page_size: int = 1000,
                    filters: Optional[dict] = None, sort: str = "_id desc") -> pd.DataFrame:
    """Page through datastore_search and return up to `max_rows` records as a DataFrame.

    Defaults to `_id desc` so a capped live pull grabs the most RECENT awards — the period
    with `number_of_bids` coverage (post-2023-06-30), making the live demo meaningful."""
    records: list = []
    while len(records) < max_rows:
        want = min(page_size, max_rows - len(records))
        result = ckan_get("datastore_search", resource_id=resource_id, limit=want,
                          offset=len(records), sort=sort,
                          **({"filters": _encode_filters(filters)} if filters else {}))
        batch = result.get("records", [])
        if not batch:
            break
        records.extend(batch)
        if len(batch) < want:
            break
        time.sleep(0.1)  # be polite to the public API
    return pd.DataFrame(records)


def _encode_filters(filters: Optional[dict]):
    import json
    return json.dumps(filters) if filters else None


# --- CanadaBuys contract history (amendment-aware turnover backbone) ------------------
# These are file (CSV) resources, NOT DataStore tables, so they are downloaded and parsed
# (D1.2). One file per fiscal year. The dataset carries amendment trails
# (amendmentNumber/amendmentType), procurement method, instrument type, GSIN, the
# government-STANDARDIZED supplier name, and the contracting entity — everything the
# structural verdict needs. It does NOT carry `number_of_bids`, and its identifiers do not
# overlap with Proactive Disclosure's (verified: 0 join-key intersection), so the bid signal
# is unavailable on this spine and verdicts fall back to the turnover/procedure/instrument
# logic (the spec's original design).
_CH_COLS = {
    "solicitation": "solicitationNumber-numeroSollicitation",
    "procurement": "procurementNumber-numeroApprovisionnement",
    "reference": "referenceNumber-numeroReference",
    "amd_num": "amendmentNumber-numeroModification",
    "amd_type": "amendmentType-typeModification-eng",
    "award_date": "contractAwardDate-dateAttributionContrat",
    "amd_date": "amendmentDate-dateModification",
    "amount": "contractAmount-montantContrat",
    "total": "totalContractValue-valeurTotaleContrat",
    "currency": "contractCurrency-contratMonnaie",
    "instrument": "instrumentType-typeInstrument-eng",
    "procedure": "procurementMethod-methodeApprovisionnement-eng",
    "gsin": "gsin-nibs",
    "unspsc": "unspsc",
    "supplier_std": "supplierStandardizedName-nomNormaliseFournisseur-eng",
    "supplier_legal": "supplierLegalName-nomLegalFournisseur-eng",
    "supplier_op": "supplierOperatingName-nomCommercialFournisseur-eng",
    "entity": "contractingEntityName-nomEntitContractante-eng",
}


def _first_nonempty(*vals):
    for v in vals:
        if v is not None and str(v).strip() and str(v).strip().lower() != "nan":
            return str(v).strip()
    return ""


def map_contract_history(df: pd.DataFrame) -> pd.DataFrame:
    """Map a raw CanadaBuys contract-history frame to the pipeline's raw schema.

    Vendor name prefers the government-standardized name, falling back to legal then
    operating name (the standardized field is ~20% filled). The contract identity used as
    `solicitationNumber` is the procurement number (stable across a contract's amendment
    rows), so the amendment logic groups amendments with their base award."""
    g = _CH_COLS
    out = pd.DataFrame(index=df.index)
    out["solicitationNumber"] = df.apply(
        lambda r: _first_nonempty(r.get(g["procurement"]), r.get(g["solicitation"]),
                                  r.get(g["reference"])), axis=1)
    out["vendorName"] = df.apply(
        lambda r: _first_nonempty(r.get(g["supplier_std"]), r.get(g["supplier_legal"]),
                                  r.get(g["supplier_op"])), axis=1)
    out["buyerName"] = df[g["entity"]].fillna("")
    out["gsin"] = df[g["gsin"]].fillna("")
    out["unspsc"] = df[g["unspsc"]].fillna("")
    out["solicitationProcedure"] = df[g["procedure"]].fillna("")
    out["instrumentType"] = df[g["instrument"]].fillna("")
    out["contractValue"] = df[g["amount"]]
    out["originalValue"] = df[g["total"]]
    out["amendmentValue"] = df[g["amount"]]
    out["currency"] = df[g["currency"]]
    # contractAwardDate and amendmentDate were historically populated interchangeably; take
    # whichever is present so turnover ordering has a date (spec §2.2).
    out["contractAwardDate"] = df.apply(
        lambda r: _first_nonempty(r.get(g["award_date"]), r.get(g["amd_date"])), axis=1)
    out["amendmentNumber"] = df[g["amd_num"]].fillna("000")
    out["amendmentType"] = df[g["amd_type"]].fillna("")
    out["numberOfBids"] = None  # not present in contract history (and not joinable from PD)
    out["pdValue"] = None
    out["source"] = "contract_history"
    out["sourceRecordId"] = df[g["reference"]].fillna("")
    return out


def fetch_contract_history(fiscal_years=("2024-2025",),
                           package_id: Optional[str] = None) -> pd.DataFrame:
    """Download the contract-history CSV(s) for the given fiscal years and map to the raw
    schema. Resource URLs are resolved via `package_show` so we follow file renames (D1.1).

    `fiscal_years` are strings like "2024-2025"; multiple years are concatenated to build a
    longer turnover backbone."""
    package_id = package_id or CKAN_DATASETS["contract_history"]
    pkg = ckan_get("package_show", id=package_id)
    wanted = {fy.lower() for fy in fiscal_years}
    urls = []
    for r in pkg.get("resources", []):
        name = (r.get("name") or "").lower()
        if (r.get("format") or "").upper() != "CSV" or "contract" not in name:
            continue
        if any(fy in name for fy in wanted):
            urls.append(r["url"])
    if not urls:
        raise RuntimeError(f"no contract-history CSV resources for {fiscal_years}")

    keep = set(_CH_COLS.values())
    frames = [pd.read_csv(io.BytesIO(_download(u)), dtype=str,
                          usecols=lambda c: c in keep, encoding="utf-8-sig",
                          on_bad_lines="skip", low_memory=False)
              for u in urls]
    raw = pd.concat(frames, ignore_index=True)
    return map_contract_history(raw)


def _download(url: str, timeout: int = 180) -> bytes:
    """Fetch a file resource. Uses a browser-style User-Agent because the CanadaBuys file
    host rejects the default urllib/requests agent with HTTP 403."""
    resp = requests.get(url, timeout=timeout,
                        headers={"User-Agent": "Mozilla/5.0 (incumbency-board data fetch)"})
    resp.raise_for_status()
    return resp.content


# --- Open tender notices (currently-posted RFPs) -------------------------------------
# Used only to link a posted RFP back to the historical competition for the same commodity
# (GSIN) and buyer. NOTE: on real data only ~5% of open notices carry a GSIN, so the precise
# link fires for a minority; the contracting entity is ~always present.
_OPEN_TENDER_COLS = {
    "solicitationNumber-numeroSollicitation": "solicitationNumber",
    "title-titre-eng": "title",
    "gsin-nibs": "gsin",
    "unspsc": "unspsc",
    "contractingEntityName-nomEntitContractante-eng": "buyerName",
    "tenderClosingDate-appelOffresDateCloture": "tenderClosingDate",
    "procurementCategory-categorieApprovisionnement": "procurementCategory",
    "procurementMethod-methodeApprovisionnement-eng": "procurementMethod",
    # Kept only for cross-file dedup (dropped before return), not part of the RFP schema.
    "referenceNumber-numeroReference": "referenceNumber",
    "amendmentNumber-numeroModification": "amendmentNumber",
}
# CanadaBuys splits currently-open tender data across TWO bulk files, and they do NOT fully
# overlap: a freshly-published (or freshly-amended) notice lands in `newTenderNotice` first and
# only propagates into `openTenderNotice` after a ~1-day ETL lag (verified: of 8 rows in the new
# file, 5 were absent from the 913-row open file). Reading only the "open" file therefore drops
# the day's newest open RFPs. We fetch both and union them, deduping on referenceNumber and
# keeping the highest amendmentNumber (the latest revision of each notice).
_OPEN_TENDER_URLS = (
    "https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv",
    "https://canadabuys.canada.ca/opendata/pub/newTenderNotice-nouvelAvisAppelOffres.csv",
)
# Back-compat alias for the primary file (some callers/tests reference it directly).
_OPEN_TENDER_URL = _OPEN_TENDER_URLS[0]


def fetch_open_tenders() -> pd.DataFrame:
    """Download the CanadaBuys open-tender bulk files and map to the RFP raw schema.

    Unions the `openTenderNotice` and `newTenderNotice` files (the latter carries the day's
    newest notices before they reach the former), deduping on referenceNumber and keeping each
    notice's latest amendment. A single file failing is tolerated as long as one succeeds."""
    keep = set(_OPEN_TENDER_COLS)
    frames = []
    errors = []
    for url in _OPEN_TENDER_URLS:
        try:
            frames.append(pd.read_csv(io.BytesIO(_download(url)), dtype=str,
                                      usecols=lambda c: c in keep, encoding="utf-8-sig",
                                      on_bad_lines="skip", low_memory=False))
        except Exception as e:  # one file down must not lose the other
            errors.append(f"{url}: {e}")
    if not frames:
        raise RuntimeError("could not fetch any open-tender file: " + "; ".join(errors))

    raw = pd.concat(frames, ignore_index=True).rename(columns=_OPEN_TENDER_COLS)

    # Dedup: keep the latest amendment per notice. amendmentNumber is a zero-padded string
    # like "000"/"001"; sort numerically (non-numeric -> -1) so the highest revision wins.
    if "referenceNumber" in raw.columns:
        amd = pd.to_numeric(raw.get("amendmentNumber"), errors="coerce").fillna(-1)
        raw = (raw.assign(_amd=amd)
                  .sort_values("_amd")
                  .drop_duplicates(subset="referenceNumber", keep="last")
                  .drop(columns="_amd"))

    return raw.drop(columns=[c for c in ("referenceNumber", "amendmentNumber")
                             if c in raw.columns]).reset_index(drop=True)


def fetch_proactive_disclosure(max_rows: int = 5000,
                               resource_id: Optional[str] = None) -> pd.DataFrame:
    """Fetch proactive-disclosure rows and map them to the raw schema the pipeline expects.

    Adds missing raw columns (currency, amendment metadata, pdValue) with safe defaults so a
    PD-only spine flows through `pipeline.build_canonical_awards` unchanged."""
    if resource_id is None:
        resource_id = (find_datastore_resource(CKAN_DATASETS["proactive_disclosure"],
                                                "Contracts over $10,000")
                       or _PD_RESOURCE_DEFAULT)
    raw = datastore_fetch(resource_id, max_rows=max_rows)
    if raw.empty:
        return raw

    out = pd.DataFrame()
    for src, dst in _PD_FIELD_MAP.items():
        out[dst] = raw[src] if src in raw.columns else None

    # PD packs BOTH coding systems into its single `commodity_code` field (~96% GSIN-style,
    # ~4% 8-digit UNSPSC). The field map lands it all in `gsin`; split it so UNSPSC codes go to
    # `unspsc`. Without this the RFP linkage — which matches mostly on UNSPSC (~84% of open
    # notices) — can never link to the PD spine, since every PD market would carry only a GSIN
    # (verified: 0 linkable before, the UNSPSC overlap is misrouted into the gsin column).
    code = out["gsin"].map(_route_commodity_code)
    out["unspsc"] = [u for u, _ in code]
    out["gsin"] = [g for _, g in code]

    out["currency"] = "CAD"            # PD is reported in CAD
    out["amendmentNumber"] = "000"     # PD has no clean amendment-number field
    out["amendmentType"] = ""
    out["pdValue"] = None
    out["source"] = "proactive_disclosure"
    out["sourceRecordId"] = raw["_id"].astype(str) if "_id" in raw.columns else out["solicitationNumber"]
    return out
