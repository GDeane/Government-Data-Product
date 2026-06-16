# Who's My Competition? (Incumbency & Market-Structure Board)

A vendor-side tool for firms that sell to the Government of Canada. For any federal commodity
market — one commodity (**UNSPSC** code, or GSIN where UNSPSC is absent) bought by one
department — it shows **who has won historically and their market share**, so a
business-development / capture lead can see their likely competition before bidding.

> **The one question the UI answers:** *"For this commodity × buyer, who are the incumbents,
> and how much of the market does each hold?"* — presented as a pie chart with the **top-1/2/3
> competitors** called out, by award value **or** by number of awards.

**The default view is "Open RFPs → competition":** pick a currently-posted RFP and the page
shows who has historically won the same commodity at the same buyer — your likely competition,
as pie charts. The RFP→history join is on **UNSPSC or GSIN** (UNSPSC preferred — ~84% of open
notices carry it vs ~5% for GSIN), so it fires for most notices; those with no commodity code
are reported as unlinkable. A second tab lets you browse the historical markets directly.

Every vendor identity is **entity-resolved**, so a firm's variants (Inc./Ltd., regional
offices, M&A) count as one competitor rather than several — which is what makes the shares
correct.

> **Earlier, broader version.** This started as a market-*structure* tool that also assigned an
> enterable / walled / ambiguous **verdict** from turnover, procedure, instrument, and the
> disclosed single-bid rate. That logic is still in the backend (and tested) but is no longer
> the focus of the UI — see "Retained backend" below and `MILESTONES.md` §9.

---

## What's signal here (retained backend, not the UI focus)

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

## Getting started

You don't need to be a programmer to run this. Do the steps **in order**, copying each grey
block into a terminal (**Terminal** on Mac/Linux, or **PowerShell** on Windows). Steps 1 and 2
are one-time setup; after that you only need step 3.

**A prebuilt database ships with the project**, so you can open the app right away — there's
**no download or build step required** to get started. (If you want fresher data later, see
"Refreshing the data" below.)

### Step 0 — Get the project onto your computer (one time)

If you haven't already, download the project. Either click the green **Code → Download ZIP**
button on the GitHub page and unzip it, or, if you have `git` installed:

```bash
git clone https://github.com/GDeane/Government-Data-Product.git
```

Everything below is run **from inside the project folder**
(`incumbency-and-market-structure-board`). On Mac/Linux you'd `cd` into it; on Windows, open the
folder and use the address bar to launch a terminal there.

### Step 1 — Install Python (one time)

Install **Python 3.10** from [python.org](https://www.python.org/downloads/) if you don't already
have it. On the Windows installer, tick **"Add Python to PATH"**.

### Step 2 — Set up the project (one time)

From inside the project folder, run:

```bash
python -m venv .venv                 # creates a private workspace for this tool
source .venv/bin/activate            # Windows instead: .venv\Scripts\activate
pip install -r requirements.txt      # installs everything it needs
```

After the second line, your prompt should start with `(.venv)` — that means the workspace is
active. If you close the terminal and come back later, just run the `activate` line again before
step 3.

### Step 3 — Open the app

```bash
streamlit run app/board.py
```

This opens **"Who's My Competition?"** in your web browser, using the prebuilt database that came
with the project. If it doesn't open automatically, copy the **Local URL** the command prints
(usually `http://localhost:8501`) into your browser.

Keep the terminal window open while you use the app; when you're done, click back into the
terminal and press `Ctrl + C` to stop it.

### Refreshing the data (optional)

The bundled database is a snapshot. To pull the latest **real Government of Canada** contract data
and rebuild it yourself, run:

```bash
python scripts/build.py --source contract_history --years 2024-2025 2023-2024 2022-2023
```

This downloads three years of contract data (plus the list of currently-open federal tenders) and
overwrites `data/market_board.duckdb`. It fetches a few hundred megabytes, so it can take a few
minutes — that's normal. When it finishes you'll see a one-line summary of how many awards,
markets, and open tenders were loaded. Re-run it any time you want fresher data, then restart the
app (step 3).

## Using the app

- **Open RFPs → competition** (the tab you land on): pick a currently-open federal tender, and the
  page shows **who has historically won the same kind of work at the same department** — your
  likely competition — as a pie chart with the top 1–3 competitors named. You can switch the share
  between **dollar value** and **number of awards**.
- **Browse historical markets**: explore the markets directly, without starting from an open
  tender.

Some open tenders can't be linked to history — either the tender doesn't list a commodity code, or
no one has bought that commodity at that department before. The app tells you when that's the case,
and by default shows you the ones that *can* be linked first.

> **A note on the numbers.** This tool covers **federal** Government of Canada tenders (~900 open at
> any time). The CanadaBuys website shows many more "Open" results because it also lists provincial,
> territorial, and municipal/school/hospital opportunities — those aren't part of the federal data
> this tool is built on.

---

## How it works

```
CanadaBuys contract history (CKAN pull)
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
scripts/build.py CLI: build the board from CanadaBuys contract history into DuckDB
tests/           53 tests incl. golden verdict cases + ER precision/recall gate
MILESTONES.md    milestone-by-milestone design-decision log
```

See `MILESTONES.md` for the full decision log, including every threshold's rationale and the
mid-build correction of the bid-count premise.
