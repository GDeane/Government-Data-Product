# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A vendor-side market-intelligence tool for firms selling to the Government of Canada. For a
federal commodity market — one commodity (UNSPSC, or GSIN where UNSPSC is absent) bought by one
department — it shows **who has won historically and their market share** (pie chart + top-1/2/3
competitors), so a capture lead can see their likely competition before bidding. A retained
backend also assigns an enterable/walled/ambiguous **verdict**; that logic is still tested but is
no longer the UI focus.

`README.md` is the product narrative; `MILESTONES.md` is the milestone-by-milestone decision log
(every threshold and design choice is referenced by a `Dx.y` tag that appears throughout the
code's docstrings).

## Commands

```bash
# Setup (built & tested on Python 3.10)
uv venv --python 3.10 && source .venv/bin/activate && uv pip install -e .
# or: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Build the DuckDB board (data/market_board.duckdb)
python scripts/build.py                                              # synthetic fixtures (offline, deterministic, default)
python scripts/build.py --source live --limit 8000                  # TBS Proactive Disclosure spine (has bid counts)
python scripts/build.py --source contract_history --years 2024-2025 # CanadaBuys amendment-aware spine (no bid counts)

streamlit run app/board.py     # explore the board (reads the DuckDB file)

# Tests
python -m pytest -q                       # full suite
python -m pytest tests/test_signals.py -q  # one file
python -m pytest tests/test_verdict_cases.py::<name> -q  # one test
```

`pytest` config lives in `pyproject.toml` (`pythonpath = ["src"]`, `testpaths = ["tests"]`), so
tests run without activating an editable install. The core suite is fully offline and
deterministic; `tests/test_ingest_live.py` auto-skips when `open.canada.ca` is unreachable.

## Architecture

The pipeline is a deterministic transform — the **same path runs for synthetic and live data**;
only the source of the raw combined table differs (`scripts/build.py` selects it). Stages, in
order (`src/incumbency/`):

```
ingest (live CKAN) / fixtures (synthetic)   → raw combined table (CanadaBuys/PD shape)
  → clean        value/date/currency/amendment/bid parsing
  → normalize    procedure/instrument/GSIN/UNSPSC enums (rule-based, never AI)
  → entities     vendor & buyer entity resolution (the showcase)
  → pipeline     build_canonical_awards → signals.compute_markets
  → store        DuckDB persistence (awards + markets + rfps tables)
  → app/board.py Streamlit UI; linkage.py joins open RFPs to historical markets
```

Key invariants to preserve when editing:

- **`awards` is the single source of truth; `markets` is always re-derivable from it.** Every
  number in `signals.py` is computed from the per-award table, never stored independently. Don't
  add a market metric that can't be recomputed from `awards`.
- **All scoring/verdict math is deterministic.** AI is confined to one place: adjudicating the
  *ambiguous* vendor-name similarity band, behind the `Adjudicator` protocol in `entities.py`.
  The default `RuleBasedAdjudicator` requires no API key; an LLM adjudicator is a drop-in for that
  band only.
- **Every tunable lives in `config.py`** (`Thresholds`, `ER_CONFIG`, `BID_MANDATE_DATE`,
  `CKAN_DATASETS`, `OPO_SINGLE_BID_PRIOR`). Contestability-score weights must sum to 1.0 — there's
  an `assert` at import. Don't scatter magic numbers into `signals.py`.
- **Entity resolution is conservative on merges.** A false merge inflates monopoly and hides
  turnover; a false split fabricates turnover. The middle similarity band that the adjudicator is
  unsure about goes to `needs_review` (kept *separate*) and surfaces in the UI as "possible same
  vendor". Accuracy is gated against `tests/labelled_vendor_pairs.py` (spec requires ≥0.95
  precision); don't loosen the bands without re-checking that gate.

### The two live spines (deliberately not merged)

Their identifiers do not overlap (measured: 0 join-key intersection), so they are separate builds,
never joined:

- **`live`** — TBS Proactive Disclosure via CKAN `datastore_search`. Carries `number_of_bids`
  (the competition signal) but flattens amendments.
- **`contract_history`** — CanadaBuys contract-history CSVs. Amendment-aware, has procedure /
  instrument / GSIN / government-standardized supplier name, but **no bid counts**, so verdicts
  fall back to turnover/procedure/instrument logic.

Live ingest (`ingest.py`) uses the CKAN action API (read-only, no key) and resolves resource ids
at runtime via `package_show` so it survives fiscal-year file renames and the 2026 restructuring —
no hard-coded file URLs, no HTML scraping.

### The bid-count signal (a corrected spec premise)

The original spec stated no federal bulk dataset exposes bid counts. That is false for the PD
spine: `number_of_bids` is mandatory since **2023-06-30** (`BID_MANDATE_DATE`). The build treats
it as first-class but honestly: it is only computed over post-mandate award events with disclosed
counts, the signal is "strong" only above a coverage threshold, and where coverage is thin it
falls back to the OPO single-bid prior as *context* (never a per-record value). This is what lets
the verdict resolve the historically ambiguous "thin field vs. strong incumbent" case instead of
merely flagging it. Note: `schema.py`'s module docstring still claims "no `num_bids` column" — that
is stale relative to the correction; the column does exist and is used.

### Verdict logic

The central rule lives in `signals.decide_verdict`: high concentration + open procedure +
near-zero turnover yields **ambiguous**, never enterable, unless the disclosed bid count resolves
it. Concentration *shortlists* a market but never decides "beatable" on its own. Golden cases for
each verdict path are in `tests/test_verdict_cases.py`; `fixtures.py` generates one synthetic
market per verdict.
