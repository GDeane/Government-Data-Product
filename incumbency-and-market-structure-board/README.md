# Incumbency & Market-Structure Board

A vendor-side, market-entry intelligence tool for firms that sell to the Government of Canada.
It turns federal procurement disclosure into **a ranked map of commodity markets by how
entrenched the sitting incumbent is and how enterable the market looks** — so a
business-development / capture lead can tell **a beatable incumbent from a walled one** before
spending scarce proposal budget.

> **The one question it answers:** *"Which commodity (GSIN) × buyer markets are worth pursuing,
> because the incumbent's position looks structurally enterable — and which are locked, or held
> by a genuinely strong incumbent rather than merely unchallenged?"*

It deliberately answers a **market-entry** question (*"is the incumbent beatable?"*), not an
**oversight** question (*"was this specific contract improperly directed?"*).

---

## What's signal here

Each `(commodity × buyer)` market gets a transparent **verdict**:

| Verdict | Meaning |
|---|---|
| 🟢 **enterable** | No entrenched incumbent, **or** a concentrated incumbent whose grip looks breakable — the winner turns over, **or** they win largely *unopposed* (a thin field you can enter). |
| 🔴 **walled** | Position held via standing-offer / call-up lock-in or sole-source / ACAN procedure — **or** the incumbent consistently *beats many real rivals* (a genuinely strong incumbent). |
| 🟡 **ambiguous** | Concentrated and open but the winner barely turns over **and** there isn't enough disclosed bid data to tell a thin field from a strong incumbent. We flag it; we don't guess. |
| ⚪ **insufficient_data** | Too few awards (or commodity coding too coarse) to say anything. |

The verdict is built from **disclosed fields only**, each re-derivable from source records:

- **Concentration** — top-1 award-value share (HHI secondary). *Shortlists; never decides.*
- **Winner turnover / dynamism** — distinct winners, lead changes over time, recency of any
  new-entrant win.
- **Procedure & instrument** — open / selective / ACAN / sole-source; contract / standing-offer /
  call-up.
- **Measured single-bid rate** *(front and center)* — from TBS Proactive Disclosure's
  `number_of_bids`, **mandatory only since 2023-06-30**, so computed over post-mandate awards and
  labelled with its coverage. This is what lets the tool *resolve* the thin-field-vs-strong-
  incumbent ambiguity instead of merely flagging it.

### Honest limits (shown in the UI, not hidden)

- **Bid coverage is recent-only.** `number_of_bids` became mandatory on **2023-06-30**; pre-that
  awards have none, so older/sparse markets fall back to the OPO prior (~29% of open / ~35% of
  limited competitive processes still drew a single bid) as *context*, never a per-record value.
- **Concentration is directionally ambiguous** and is never labelled "beatable" on its own.
- **No overcharging claims** (no unit-price benchmark) and **no per-contract integrity claims**.
- **Entity resolution is never perfect** — residual error is flagged ("possible same vendor"),
  not hidden, because it distorts both concentration and turnover.

> **A note on the spec.** The original requirements stated that *no* federal bulk dataset exposes
> bid counts. That turned out to be true only for the historical backbone — TBS Proactive
> Disclosure exposes `number_of_bids` and populates it well from 2023 on. This build surfaces that
> discovery and treats the field as first-class. See `MILESTONES.md` §7.

---

## Quick start

```bash
# 0) Create and activate a virtual environment, then install (using uv)
uv venv --python 3.10        # built & tested on Python 3.10
source .venv/bin/activate    # Windows: .venv\Scripts\activate
uv pip install -e .          # installs the package + deps; no PYTHONPATH needed

# (or with plain pip)
# python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 1) Build the board into DuckDB (synthetic fixtures — offline, deterministic, ~instant)
python scripts/build.py

# 2) Or build from REAL Government of Canada data via the CKAN API (read-only, no key)
python scripts/build.py --source live --limit 8000             # PD spine — has bid counts
python scripts/build.py --source contract_history --years 2024-2025  # amendment-aware spine

# 3) Explore the ranked board
streamlit run app/board.py

# 4) Run the tests
python -m pytest -q
```

`scripts/build.py` writes `data/market_board.duckdb` with two tables — `awards` (canonical
per-award, the source of truth) and `markets` (aggregated metrics + verdict). The Streamlit app
reads that file.

---

## How it works

```
CKAN pull / synthetic fixtures
        │
        ▼
  clean (values, dates, currency, amendments)      ── deterministic
        ▼
  normalize (procedure / instrument / GSIN enums)  ── rule-based, never AI
        ▼
  entity-resolve vendors & buyers                  ── rapidfuzz + pluggable adjudicator
        ▼                                              (+ M&A crosswalk; conservative on merges)
  compute signals  (concentration, turnover, bid   ── deterministic
   metrics, contestability score, verdict)
        ▼
  DuckDB  ──►  Streamlit board (drill-down + provenance + ambiguity note + OPO prior)
```

- **Ingestion** uses the CKAN action API on `open.canada.ca` (read-only, no key); `package_show`
  resolves current resource ids so it survives fiscal-year renames and the 2026 restructuring. No
  HTML scraping. There are **two live spines, deliberately not merged** because their identifiers
  do not overlap (measured: 0 join-key intersection):
  - **`live`** — TBS Proactive Disclosure (`datastore_search`): carries `number_of_bids` (the
    competition signal), but flattens amendments.
  - **`contract_history`** — CanadaBuys contract history (CSV download): amendment-aware award
    events, procurement method, instrument, GSIN, and the government-standardized supplier name —
    but no bid counts, so verdicts fall back to the turnover/procedure/instrument logic.
  Joining bid counts onto the amendment-aware spine is not possible from published keys; see
  `MILESTONES.md` §8.
- **AI usage** is confined to adjudicating *ambiguous* vendor-name pairs, behind an `Adjudicator`
  interface. The **default adjudicator is deterministic** (rule-based), so everything runs with no
  API key; an LLM adjudicator can be dropped in for the ambiguous band only. All concentration,
  turnover, bid, score, and verdict math is deterministic.

## Entity resolution — the hard problem, measured

A false *merge* inflates apparent monopoly and hides turnover; a false *split* fabricates phantom
turnover. So the resolver is conservative on merges (defaults to *not* merging when unsure) and its
accuracy is **measured** against a hand-labelled set (`tests/labelled_vendor_pairs.py`):

> **precision 1.000 / recall 0.867** (0 false merges) — clears the spec's ≥0.95 precision gate.

Unresolved near-duplicates that affect a market's winner set are surfaced to the user as
"possible same vendor", so phantom turnover is visible rather than silent.

---

## Layout

```
src/incumbency/
  config.py      thresholds, CKAN ids, BID_MANDATE_DATE, OPO prior (all tunables in one place)
  schema.py      canonical award + market columns and controlled vocabularies
  ingest.py      live CKAN pull (DataStore + package_show)
  clean.py       value/date/currency/amendment/bid parsing
  normalize.py   procedure / instrument / GSIN classification (rule-based)
  entities.py    vendor & buyer entity resolution (the showcase)
  signals.py     concentration, turnover, bid metrics, contestability score, verdict
  pipeline.py    raw -> canonical awards -> markets
  store.py       DuckDB persistence + provenance lookup
  fixtures.py    deterministic synthetic dataset (one market per verdict)
app/board.py     Streamlit ranked board with drill-down
scripts/build.py CLI: build synthetic or live into DuckDB
tests/           39 tests incl. golden verdict cases + ER precision/recall gate
MILESTONES.md    milestone-by-milestone design-decision log
```

See `MILESTONES.md` for the full decision log, including every threshold's rationale and the
mid-build correction of the bid-count premise.
