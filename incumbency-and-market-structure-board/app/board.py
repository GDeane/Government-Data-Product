"""Streamlit market-structure board (Milestone 5).

Run:  streamlit run app/board.py
Reads the DuckDB built by `scripts/build.py`. Surfaces, front and center: the verdict, the
measured single-bid rate (D7), provenance, confounders, the directional-ambiguity note, and
the OPO prior — so every claim is traceable and every limit is visible (NFR1/NFR2)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incumbency import store  # noqa: E402
from incumbency.config import BID_MANDATE_DATE, DUCKDB_PATH, OPO_SINGLE_BID_PRIOR  # noqa: E402

st.set_page_config(page_title="Incumbency & Market-Structure Board", layout="wide")

_VERDICT_STYLE = {
    "enterable": ("🟢", "#1a7f37"),
    "walled": ("🔴", "#b42318"),
    "ambiguous": ("🟡", "#b54708"),
    "insufficient_data": ("⚪", "#667085"),
}


@st.cache_data(show_spinner=False)
def _load(db_path: str):
    markets = store.load_markets(db_path)
    return markets


def _verdict_badge(v: str) -> str:
    icon, _ = _VERDICT_STYLE.get(v, ("•", "#000"))
    return f"{icon} {v}"


def _pct(x):
    return "—" if x is None or pd.isna(x) else f"{float(x):.0%}"


def main() -> None:
    st.title("Incumbency & Market-Structure Board")
    st.caption("Which federal commodity markets are worth pursuing — is the incumbent's "
               "position structurally **enterable** or **walled**?")

    # --- The honest framing, stated plainly (NFR2) ---
    with st.expander("What this tool does and does NOT claim — read me", expanded=False):
        st.markdown(
            f"""
This maps federal commodity markets by **market structure** — how concentrated the winners
are, whether the winner ever changes (**turnover**), how work is procured, and through what
instrument — to answer a **market-entry** question: *is the incumbent beatable?*

**Bid counts (front and center).** TBS Proactive Disclosure now discloses
`number_of_bids`. It became a **permanent, mandatory** requirement on **{BID_MANDATE_DATE:%B %d, %Y}**,
so coverage exists only for awards on/after that date; the measured single-bid rate is
computed over those awards. Where coverage is thin, the OPO prior
(~{OPO_SINGLE_BID_PRIOR['open_competitive']:.0%} of open / ~{OPO_SINGLE_BID_PRIOR['limited']:.0%}
of limited competitive processes still drew a single bid) is the only context — a reminder
that an *open* label is not proof of a real contest.

**Concentration is directionally ambiguous.** A single dominant winner under an open
procedure can mean a *thin field* (enterable) **or** a *strong incumbent* (hard target).
Turnover and the disclosed bid count are what separate them; where neither can, the market is
labelled **ambiguous**, never *beatable*.

**Not claimed:** that an incumbent overcharges (no unit-price benchmark); that any specific
contract was improperly directed; nor that concentration alone proves a thin field.
""")

    # --- Data source ---
    db_path = st.sidebar.text_input("DuckDB path", value=str(DUCKDB_PATH))
    if not Path(db_path).exists():
        st.warning(f"No database at `{db_path}`. Build one first:\n\n"
                   "`python scripts/build.py`  (synthetic, offline)\n\n"
                   "`python scripts/build.py --source live --limit 8000`  (real CKAN data)")
        st.stop()

    markets = _load(db_path)
    if markets.empty:
        st.info("No markets in the database.")
        st.stop()

    # --- Filters ---
    st.sidebar.header("Filter")
    verdicts = sorted(markets["verdict"].unique())
    chosen = st.sidebar.multiselect("Verdict", verdicts, default=verdicts)
    gsin_query = st.sidebar.text_input("Commodity (GSIN starts with)", "")
    min_awards = st.sidebar.slider("Minimum awards", 1, int(markets["n_awards"].max()), 1)
    only_covered = st.sidebar.checkbox("Only markets with a measured bid signal", False)

    view = markets[markets["verdict"].isin(chosen)]
    view = view[view["n_awards"] >= min_awards]
    if gsin_query:
        view = view[view["gsin"].astype(str).str.upper().str.startswith(gsin_query.upper())]
    if only_covered:
        view = view[view["bid_signal"] == "strong"]

    st.subheader(f"Ranked markets ({len(view)})")
    st.caption("Ranked by contestability score. Concentration shortlists; turnover, "
               "procedure, instrument, and the measured single-bid rate decide the verdict.")

    table = view.assign(
        verdict=view["verdict"].map(_verdict_badge),
        top1=view["top1_share"].map(_pct),
        single_bid=view["single_bid_rate"].map(_pct),
        coverage=view["bid_coverage"].map(_pct),
    )[["gsin", "buyer_canonical", "verdict", "contestability_score", "top1_share",
       "top1_vendor", "distinct_winners", "lead_changes", "single_bid_rate", "bid_signal",
       "n_awards", "confidence"]]
    table = table.rename(columns={
        "gsin": "GSIN", "buyer_canonical": "Buyer", "verdict": "Verdict",
        "contestability_score": "Score", "top1_share": "Top-1 share",
        "top1_vendor": "Incumbent", "distinct_winners": "Winners",
        "lead_changes": "Lead chgs", "single_bid_rate": "Single-bid rate",
        "bid_signal": "Bid signal", "n_awards": "Awards", "confidence": "Confidence"})
    st.dataframe(table, use_container_width=True, hide_index=True,
                 column_config={
                     "Top-1 share": st.column_config.NumberColumn(format="%.0f%%"),
                     "Single-bid rate": st.column_config.NumberColumn(
                         format="%.0f%%",
                         help=f"Measured share of single-bid awards (post-{BID_MANDATE_DATE:%Y-%m-%d})"),
                     "Score": st.column_config.NumberColumn(format="%.1f"),
                 })

    # --- Drill-down ---
    st.divider()
    labels = view.apply(lambda r: f"{r['gsin']} — {r['buyer_canonical']}", axis=1).tolist()
    if not labels:
        return
    pick = st.selectbox("Inspect a market", labels)
    row = view.iloc[labels.index(pick)]
    _render_detail(row, db_path)


def _render_detail(row: pd.Series, db_path: str) -> None:
    icon, color = _VERDICT_STYLE.get(row["verdict"], ("•", "#000"))
    st.markdown(f"### {row['gsin']} — {row['buyer_canonical']}")
    st.markdown(f"<h2 style='color:{color};margin-top:-8px'>{icon} {row['verdict'].upper()}"
                f"</h2>", unsafe_allow_html=True)
    st.write(f"**Why:** {row['verdict_reason']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Top-1 share", _pct(row["top1_share"]), help="Headline concentration")
    c2.metric("Distinct winners", int(row["distinct_winners"]))
    c3.metric("Lead changes", int(row["lead_changes"]))
    c4.metric("Contestability", f"{row['contestability_score']:.1f}")

    # --- Bid-count signal, front and center (D7) ---
    st.markdown("#### Competition signal (disclosed bid counts)")
    b1, b2, b3 = st.columns(3)
    b1.metric("Single-bid rate", _pct(row["single_bid_rate"]),
              help="MEASURED — share of post-mandate awards that drew exactly one bid")
    b2.metric("Bid coverage", _pct(row["bid_coverage"]),
              help=f"Post-{BID_MANDATE_DATE:%Y-%m-%d} awards with a disclosed bid count")
    b3.metric("Median bids", "—" if pd.isna(row["median_bids"]) else f"{row['median_bids']:g}")
    if row.get("competition_note"):
        st.info(row["competition_note"])
    opo = OPO_SINGLE_BID_PRIOR
    st.caption(f"OPO prior (context, not measured): ~{opo['open_competitive']:.0%} of open and "
               f"~{opo['limited']:.0%} of limited competitive federal processes still drew a "
               f"single bid. Source: {opo['source']}.")

    if row["verdict"] == "ambiguous" and row.get("ambiguity_note"):
        st.warning(f"**Directional ambiguity:** {row['ambiguity_note']}")

    if row.get("confounders"):
        st.markdown("**Confounders / benign explanations present:**")
        for c in row["confounders"]:
            st.markdown(f"- {c}")

    if row.get("possible_same_vendor"):
        st.markdown("**Possible same vendor (unresolved — may affect turnover):**")
        for a, b, sc in row["possible_same_vendor"]:
            st.markdown(f"- `{a}` ≟ `{b}`  (similarity {sc:.0f}) — kept separate; verify")

    with st.columns(2)[0]:
        st.markdown("**Procedure mix (by value):** " +
                    ", ".join(f"{k} {v:.0%}" for k, v in (row["procedure_mix"] or {}).items()))
        st.markdown("**Instrument mix (by value):** " +
                    ", ".join(f"{k} {v:.0%}" for k, v in (row["instrument_mix"] or {}).items()))

    # --- Provenance (NFR1): the underlying award records ---
    st.markdown("#### Provenance — underlying award records")
    awards = store.awards_for_solicitations(row["solicitation_numbers"], db_path)
    if not awards.empty:
        show = awards[["solicitation_number", "vendor_canonical", "award_value_cad",
                       "procedure_class", "instrument_class", "num_bids", "award_date",
                       "source", "confidence_flags"]].sort_values("award_date")
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.caption(f"{len(awards)} source records. Every metric above is re-derivable from "
                   "these rows (NFR3).")


if __name__ == "__main__":
    main()
