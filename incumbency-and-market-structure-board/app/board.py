"""'Who's My Competition?' — Streamlit page.

For a federal commodity market (GSIN × buyer), show who has won historically and their market
share, as a pie chart with the top-1/2/3 competitors called out. Optionally, link a
currently-posted RFP to the historical competition for the same commodity + buyer.

Share can be viewed by award value ($) or by number of awards. All vendor identities are
entity-resolved, so a firm's variants (Inc./Ltd., regional offices, M&A) count as one."""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incumbency import linkage, store  # noqa: E402
from incumbency.config import DUCKDB_PATH  # noqa: E402

st.set_page_config(page_title="Who's My Competition?", layout="wide")

_SHARE_BASIS = {
    "Award value ($)": ("value_share", "value", "% of award value"),
    "Number of awards": ("count_share", "awards", "% of awards"),
}


@st.cache_data(show_spinner=False)
def _load(db_path: str, mtime: float):
    # mtime is part of the cache key so a rebuilt DB at the same path reloads automatically.
    markets = store.load_markets(db_path)
    rfps = store.load_rfps(db_path)
    if not rfps.empty and not markets.empty:
        # Precompute each RFP's link precision once (drives the default-to-linkable view).
        prec, mon = [], []
        for _, r in rfps.iterrows():
            m = linkage.match_rfp_to_markets(r.get("unspsc"), r.get("gsin"),
                                             r.get("buyer_canonical"), markets)
            prec.append(m.precision)
            mon.append(m.matched_on)
        rfps = rfps.assign(_precision=prec, _matched_on=mon)
    return markets, rfps


def _pct(x):
    return "—" if x is None or pd.isna(x) else f"{float(x):.0%}"


def _commodity_label(row) -> str:
    """e.g. 'UNSPSC 80101500' or 'GSIN D302A' — the market's commodity key + its type."""
    ctype = str(row.get("commodity_type") or "").upper()
    return f"{ctype + ' ' if ctype else ''}{row['commodity']}"


def _pie_df(vendor_shares, share_field, topn):
    df = pd.DataFrame(vendor_shares)
    if df.empty:
        return df
    df = df.sort_values(share_field, ascending=False).reset_index(drop=True)
    if len(df) > topn:
        head = df.iloc[:topn][["vendor", share_field]].copy()
        other_val = float(df.iloc[topn:][share_field].sum())
        head = pd.concat([head, pd.DataFrame(
            [{"vendor": f"Other ({len(df) - topn} firms)", share_field: other_val}])],
            ignore_index=True)
        return head
    return df[["vendor", share_field]]


def _render_competition(row: pd.Series, basis_label: str, topn: int) -> None:
    share_field, _value_col, share_caption = _SHARE_BASIS[basis_label]
    st.markdown(f"### {_commodity_label(row)} — {row['buyer_canonical']}")
    ref = []
    if str(row.get("unspsc") or ""):
        ref.append(f"UNSPSC {row['unspsc']}")
    if str(row.get("gsin") or ""):
        ref.append(f"GSIN {row['gsin']}")
    st.caption(f"{int(row['n_awards'])} historical awards · "
               f"{int(row['distinct_winners'])} distinct winners · "
               f"${row['total_value_cad']:,.0f} total awarded"
               + (f"  ·  {' / '.join(ref)}" if ref else ""))

    # Top-3 competitor callouts (by award value — the headline ranking).
    c1, c2, c3 = st.columns(3)
    c1.metric(f"#1  {row['top1_vendor']}", _pct(row["top1_share"]))
    if row.get("top2_vendor"):
        c2.metric(f"#2  {row['top2_vendor']}", _pct(row["top2_share"]))
    if row.get("top3_vendor"):
        c3.metric(f"#3  {row['top3_vendor']}", _pct(row["top3_share"]))

    pie_df = _pie_df(row["vendor_shares"], share_field, topn)
    if not pie_df.empty:
        chart = (alt.Chart(pie_df)
                 .mark_arc(innerRadius=60)
                 .encode(
                     theta=alt.Theta(f"{share_field}:Q", stack=True),
                     color=alt.Color("vendor:N", title="Competitor",
                                     sort=pie_df["vendor"].tolist()),
                     tooltip=["vendor:N",
                              alt.Tooltip(f"{share_field}:Q", format=".1%", title="share")])
                 .properties(height=360, title=f"Market share — {share_caption}"))
        st.altair_chart(chart, use_container_width=True)

    # Full competitor table (both bases shown). Shares are fractions (0..1); convert to
    # percentage points for display so "%.1f%%" reads correctly (e.g. 0.7018 -> 70.2%).
    tbl = pd.DataFrame(row["vendor_shares"])
    if not tbl.empty:
        tbl = tbl.assign(value_share=(tbl["value_share"] * 100).round(1),
                         count_share=(tbl["count_share"] * 100).round(1))
        tbl = tbl.rename(columns={"vendor": "Competitor", "value": "Award value ($)",
                                  "value_share": "Value share %", "awards": "Awards won",
                                  "count_share": "Award-count share %"})
        st.dataframe(tbl, use_container_width=True, hide_index=True,
                     column_config={
                         "Award value ($)": st.column_config.NumberColumn(format="$%,.0f"),
                         "Value share %": st.column_config.NumberColumn(format="%.1f%%"),
                         "Award-count share %": st.column_config.NumberColumn(
                             format="%.1f%%")})

    with st.expander("Provenance — underlying award records"):
        awards = store.awards_for_solicitations(row["solicitation_numbers"],
                                                st.session_state["_db"])
        if not awards.empty:
            show = awards[["solicitation_number", "vendor_canonical", "award_value_cad",
                           "award_date", "source"]].sort_values("award_date")
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.caption("Market share above is computed from exactly these records, after "
                       "resolving vendor-name variants to one entity each.")

    with st.expander("Advanced: experimental market-structure read (not the focus)"):
        st.caption("Kept from an earlier iteration; not part of the competition view.")
        st.write(f"Verdict **{row.get('verdict','—')}** · "
                 f"contestability {row.get('contestability_score','—')} · "
                 f"HHI {row.get('hhi','—')}")


def _markets_tab(markets: pd.DataFrame, basis_label: str, topn: int) -> None:
    g1, g2, g3, g4 = st.columns([2, 2, 2, 2])
    commodity_q = g1.text_input("Commodity code (UNSPSC/GSIN) starts with", "",
                                key="mk_commodity")
    buyer_q = g2.text_input("Buyer contains", "", key="mk_buyer")
    vendor_q = g3.text_input("Incumbent / competitor contains", "", key="mk_vendor")
    min_awards = g4.slider("Minimum awards", 1, max(2, int(markets["n_awards"].max())), 1,
                           key="mk_min_awards")

    view = markets[markets["n_awards"] >= min_awards]
    if commodity_q:
        view = view[view["commodity"].astype(str).str.upper().str.startswith(
            commodity_q.upper())]
    if buyer_q:
        view = view[view["buyer_canonical"].astype(str).str.contains(buyer_q, case=False)]
    if vendor_q:
        mask = view["vendor_shares"].apply(
            lambda ss: any(vendor_q.lower() in s["vendor"].lower() for s in ss))
        view = view[mask]
    view = view.sort_values("total_value_cad", ascending=False)

    st.subheader(f"Historical markets ({len(view)})")
    st.caption("A market is one commodity (UNSPSC, or GSIN where UNSPSC is absent) bought by "
               "one department. Click a market below to see who competes for it.")
    table = view.assign(
        top1=view["top1_share"].map(_pct), top2=view["top2_share"].map(_pct),
        top3=view["top3_share"].map(_pct))[
        ["commodity", "commodity_type", "buyer_canonical", "top1_vendor", "top1",
         "top2_vendor", "top2", "top3_vendor", "top3", "distinct_winners", "n_awards",
         "total_value_cad"]]
    table = table.rename(columns={
        "commodity": "Commodity", "commodity_type": "Type", "buyer_canonical": "Buyer",
        "top1_vendor": "#1 incumbent", "top1": "#1 share", "top2_vendor": "#2",
        "top2": "#2 share", "top3_vendor": "#3", "top3": "#3 share",
        "distinct_winners": "Winners", "n_awards": "Awards", "total_value_cad": "Market $"})
    st.dataframe(table, use_container_width=True, hide_index=True,
                 column_config={"Market $": st.column_config.NumberColumn(format="$%,.0f")})

    if view.empty:
        return
    st.divider()
    labels = view.apply(lambda r: f"{_commodity_label(r)} — {r['buyer_canonical']}",
                        axis=1).tolist()
    pick = st.selectbox("Inspect a market — who's my competition?", labels, key="mk_pick")
    _render_competition(view.iloc[labels.index(pick)], basis_label, topn)


def _rfp_match(rfp, markets):
    return linkage.match_rfp_to_markets(rfp.get("unspsc"), rfp.get("gsin"),
                                        rfp.get("buyer_canonical"), markets)


def _rfps_tab(markets: pd.DataFrame, rfps: pd.DataFrame, basis_label: str, topn: int) -> None:
    st.subheader("Start here: a currently-posted RFP → who you'd compete against")
    st.info("Pick an open RFP to see who has historically won the **same commodity at the "
            "same buyer**. Joined by **UNSPSC or GSIN** (UNSPSC preferred — it's on ~84% of "
            "open notices vs ~5% for GSIN); notices with no commodity code can't be linked.")
    if rfps.empty:
        st.caption("No open RFPs loaded. Build with a live source (contract_history / live).")
        return

    has_prec = "_precision" in rfps.columns
    n_linkable = int((rfps["_precision"] != "none").sum()) if has_prec else 0

    # Filters (live data has ~900 open notices). Default to LINKABLE so the landing view
    # actually shows historical competition (pies), not "can't link" notices.
    f1, f2, f3 = st.columns([2, 2, 1])
    title_q = f1.text_input("Title contains", "", key="rfp_title")
    buyer_q = f2.text_input("Buyer contains", "", key="rfp_buyer")
    only_linkable = f3.checkbox(f"Only linkable ({n_linkable})", value=has_prec,
                                key="rfp_only_linkable",
                                help="Show only RFPs that match historical competition")

    view = rfps
    if title_q:
        view = view[view["title"].astype(str).str.contains(title_q, case=False, na=False)]
    if buyer_q:
        view = view[view["buyer_canonical"].astype(str).str.contains(buyer_q, case=False,
                                                                      na=False)]
    if only_linkable and has_prec:
        view = view[view["_precision"] != "none"]
    # Linked first (exact, then commodity), then soonest-closing.
    if has_prec:
        order = {"exact": 0, "commodity": 1, "none": 2}
        view = view.assign(_o=view["_precision"].map(order)).sort_values(
            ["_o", "closing_date"]).drop(columns="_o")

    st.caption(f"{len(view)} of {len(rfps)} open RFPs shown "
               f"({n_linkable} link to historical competition).")
    cols = ["solicitation_number", "title", "unspsc", "gsin", "buyer_canonical",
            "closing_date"] + (["_precision"] if has_prec else [])
    rfp_table = view[cols].rename(columns={
        "solicitation_number": "Solicitation", "title": "Title", "unspsc": "UNSPSC",
        "gsin": "GSIN", "buyer_canonical": "Buyer", "closing_date": "Closes",
        "_precision": "Link"})
    st.dataframe(rfp_table, use_container_width=True, hide_index=True)

    if view.empty:
        st.caption("No RFPs match these filters.")
        return
    labels = view.apply(
        lambda r: f"{r['solicitation_number']} — {str(r['title'])[:70]}", axis=1).tolist()
    pick = st.selectbox("Inspect an RFP → see the historical competition", labels,
                        key="rfp_pick")
    rfp = view.iloc[labels.index(pick)]
    match = _rfp_match(rfp, markets)

    if match.precision == "none":
        if not str(rfp.get("unspsc") or "").strip() and not str(rfp.get("gsin") or "").strip():
            st.warning("This notice has **no commodity code (UNSPSC or GSIN)**, so we can't "
                       "identify the historical market.")
        else:
            st.warning(f"No historical awards found for this notice's commodity "
                       f"(UNSPSC {rfp.get('unspsc') or '—'} / GSIN {rfp.get('gsin') or '—'}, "
                       f"buyer {rfp['buyer_canonical']}). Nothing to compare against yet.")
        return

    precision_msg = ("same commodity **and** buyer" if match.precision == "exact"
                     else "same commodity, **any buyer** (buyer didn't match exactly)")
    st.success(f"Matched to historical work on **{match.matched_on.upper()}** — "
               f"{precision_msg}. Your likely competition:")
    mkts = match.markets.sort_values("n_awards", ascending=False)
    if len(mkts) == 1:
        chosen = mkts.iloc[0]
    else:
        blabels = mkts.apply(
            lambda r: f"{r['buyer_canonical']} ({int(r['n_awards'])} awards)",
            axis=1).tolist()
        bpick = st.selectbox("This commodity was bought by several departments — pick one:",
                             blabels, key="rfp_market_pick")
        chosen = mkts.iloc[blabels.index(bpick)]
    _render_competition(chosen, basis_label, topn)


def main() -> None:
    st.title("Who's My Competition?")
    st.caption("For a federal commodity market, see who's won historically and their market "
               "share. Vendor names are entity-resolved, so a firm's variants count as one.")

    db_path = st.sidebar.text_input("DuckDB path", value=str(DUCKDB_PATH))
    st.session_state["_db"] = db_path
    if not Path(db_path).exists():
        st.warning(f"No database at `{db_path}`. Build one first:\n\n"
                   "`python scripts/build.py`  (synthetic, offline)\n\n"
                   "`python scripts/build.py --source contract_history --years 2024-2025`")
        st.stop()

    markets, rfps = _load(db_path, Path(db_path).stat().st_mtime)
    if markets.empty:
        st.info("No markets in the database.")
        st.stop()

    basis_label = st.sidebar.radio("Market share by", list(_SHARE_BASIS), index=0)
    topn = st.sidebar.slider("Competitors shown in pie (rest = 'Other')", 3, 15, 8)

    # Open RFPs → competition is the default (first) tab.
    tab_rfps, tab_markets = st.tabs(["Open RFPs → competition", "Browse historical markets"])
    with tab_rfps:
        _rfps_tab(markets, rfps, basis_label, topn)
    with tab_markets:
        _markets_tab(markets, basis_label, topn)


if __name__ == "__main__":
    main()
