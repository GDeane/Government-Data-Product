"""Network-gated smoke test for the live CKAN path (D0.1).

Skipped automatically when open.canada.ca is unreachable, so the core suite stays offline
and deterministic. When network is available it confirms the real DataStore still exposes the
fields we depend on — including `number_of_bids` (the field the spec assumed absent)."""

import pytest
import requests

from incumbency import ingest, pipeline
from incumbency.config import CKAN_BASE


def _online() -> bool:
    try:
        requests.get(f"{CKAN_BASE}/status_show", timeout=8).raise_for_status()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _online(), reason="open.canada.ca unreachable (offline)")


def test_live_pull_builds_markets():
    raw = ingest.fetch_proactive_disclosure(max_rows=500)
    assert not raw.empty
    # The fields the build depends on are present after mapping.
    for col in ("vendorName", "buyerName", "gsin", "solicitationProcedure",
                "contractValue", "contractAwardDate", "numberOfBids"):
        assert col in raw.columns
    result = pipeline.run_pipeline(raw)
    assert not result.markets.empty
    assert set(result.markets["verdict"]).issubset(
        {"enterable", "walled", "ambiguous", "insufficient_data"})


def test_contract_history_spine_is_amendment_aware():
    """The CanadaBuys contract-history spine downloads, maps, and exercises the amendment
    logic on real data (amendment rows are excluded from award-event counts)."""
    raw = ingest.fetch_contract_history(fiscal_years=("2024-2025",))
    assert not raw.empty
    assert (raw["numberOfBids"].isna()).all()  # no bid counts on this spine
    result = pipeline.run_pipeline(raw)
    # Real contract history is ~40-46% amendment rows; confirm some were detected and that
    # base award events are fewer than total rows (the dedup actually happened).
    assert int(result.awards["is_amendment"].sum()) > 0
    base_events = int((~result.awards["is_amendment"] &
                       ~result.awards["is_admin_amendment"]).sum())
    assert base_events < len(result.awards)
    assert not result.markets.empty


def test_number_of_bids_is_actually_populated_recently():
    """Guards the central data finding: number_of_bids exists and is populated in recent
    proactive-disclosure data (contradicting the original spec premise)."""
    raw = ingest.fetch_proactive_disclosure(max_rows=500)  # most recent (sort _id desc)
    filled = raw["numberOfBids"].apply(
        lambda v: str(v).strip() not in ("", "None", "nan")).mean()
    assert filled > 0.5, f"expected recent bid coverage >50%, got {filled:.0%}"
