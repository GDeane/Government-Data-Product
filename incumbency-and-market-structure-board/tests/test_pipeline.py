"""End-to-end pipeline + hand-verification + provenance tests (D6.2 / NFR1 / NFR3)."""

from datetime import date

import pytest

from incumbency import fixtures, pipeline, store

TODAY = date(2026, 6, 15)


@pytest.fixture(scope="module")
def result():
    return pipeline.run_pipeline(fixtures.generate_raw_awards(), today=TODAY)


def test_entity_resolution_collapses_acme(result):
    """All Acme surface variants resolve to a single canonical entity in the D302A market —
    the thing that makes its concentration & turnover real rather than phantom."""
    d302a = result.awards[result.awards["gsin"] == "D302A"]
    acme_raw = {"Acme Inc.", "Acme Inc", "ACME INCORPORATED", "Acme Ltd.",
                "Acme Inc. (Ottawa)"}
    canon = set(d302a[d302a["vendor_raw"].isin(acme_raw)]["vendor_canonical"])
    assert len(canon) == 1, f"Acme variants split across {canon}"


def test_value_conflict_flagged_not_resolved(result):
    flagged = result.awards[result.awards["confidence_flags"].apply(
        lambda fl: "value_conflict" in fl)]
    assert len(flagged) >= 1  # the PD vs CanadaBuys disagreement is surfaced


def test_department_canonicalization(result):
    # "PSPC" and the full name both fold into the canonical department.
    buyers = set(result.awards[result.awards["gsin"] == "D302A"]["buyer_canonical"])
    assert buyers == {"Public Services and Procurement Canada"}


def test_hand_verified_concentration_and_turnover(result):
    """Recompute the D302A headline numbers by hand from the engineered fixture and assert
    the pipeline matches (spec §2.4 verification step)."""
    m = result.markets
    d302a = m[m["gsin"] == "D302A"].iloc[0]
    # Hand totals (non-admin value, Acme collapsed): Acme 2350k+220k(PSPC)+50k(fin amend)
    # +275k(conflict base) ; Globex 550k ; Cedar 500k ; Birchwood 180k.
    acme = 2_350_000 + 220_000 + 50_000 + 275_000
    total = acme + 550_000 + 500_000 + 180_000
    assert d302a["top1_vendor"].lower().startswith("acme")
    assert round(d302a["top1_share"], 3) == round(acme / total, 3)
    assert d302a["distinct_winners"] == 4   # Acme, Globex, Cedar, Birchwood
    assert d302a["lead_changes"] == 1       # Globex led, then Acme overtook


def test_store_roundtrip_and_provenance(result, tmp_path):
    db = tmp_path / "t.duckdb"
    store.save(result.awards, result.markets, db)
    markets = store.load_markets(db)
    assert len(markets) == len(result.markets)
    # Complex columns survive the JSON round-trip as Python objects.
    row = markets[markets["gsin"] == "D302A"].iloc[0]
    assert isinstance(row["solicitation_numbers"], list)
    assert isinstance(row["procedure_mix"], dict)
    # Provenance lookup returns the underlying award records (NFR1).
    awards = store.awards_for_solicitations(row["solicitation_numbers"], db)
    assert len(awards) >= d302a_award_count(result)


def d302a_award_count(result):
    return int((result.awards["gsin"] == "D302A").sum())
