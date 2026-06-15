# Milestones & Design Decisions Log

This document tracks the build of the **Incumbency & Market-Structure Board** milestone by
milestone, and records every non-obvious design decision with its rationale. It is the place to
look to understand *why* the code is shaped the way it is.

The product answers one question — **"is this incumbent's position structurally enterable?"** — and
deliberately does **not** answer the oversight question **"was this contract actually competed?"**
That boundary drives most decisions below.

---

## Milestone 0 — Foundations & scaffolding

**Goal:** Reproducible skeleton: package layout, dependencies, config, milestone log.

**Decisions**

- **D0.1 — Offline-first, live-capable.** The pipeline operates on a canonical award DataFrame. We
  ship (a) a real CKAN ingestion path (`--source live`) and (b) a deterministic synthetic fixture
  generator (`--source synthetic`, the default). Rationale: the real federal datasets are
  130k–574k rows and lag/restructure; a multi-GB download must not be on the critical path for
  tests or the demo. Tests and the golden-path demo run fully offline and reproducibly; the live
  path is exercised by a thin smoke test that is skipped without network. This directly satisfies
  NFR5 (runs from README) without coupling correctness to a flaky external service.
- **D0.2 — DuckDB single-file store.** Zero infra, analytics-fast, matches spec §5.1.
- **D0.3 — Streamlit frontend.** Spec §5.1 names it the fastest path to the ranked board.
- **D0.4 — Package name `incumbency`** under `src/` layout; CLI entry via `scripts/build.py`.

---

## Milestone 1 — Ingestion (CKAN, no API key)

**Goal:** Pull the federal datasets without scraping; document the no-bid-count constraint.

**Decisions**

- **D1.1 — CKAN action API, read-only, no key.** `package_show` + file download for the CanadaBuys
  award / contract-history / tender file datasets (robust to fiscal-year renames and the 2026
  restructuring); `datastore_search` for DataStore-backed proactive disclosure. No HTML scraping
  (spec §2.3).
- **D1.2 — Per-resource DataStore check.** Not every resource is DataStore-queryable; ingestion
  probes `datastore_search` and falls back to file download per resource (spec §2.3 caveat).
- **D1.3 — Field presence is verified, not assumed.** The 2026 `instrumentType` / `amendmentType`
  fields are checked at ingest; if absent we degrade gracefully (instrument defaults to `contract`,
  admin-amendment dedupe falls back to value-based heuristics). Recorded as an open-question
  resolution.
- **D1.4 — No bid-count field exists.** Confirmed assumption baked into the schema: there is no
  `num_bids` column anywhere. The pipeline never fabricates one. This is the headline scope
  boundary.

---

## Milestone 2 — Clean & normalize

**Goal:** Canonical per-award table joined on `solicitation_number`.

**Decisions**

- **D2.1 — Join on `solicitation_number` only.** Reference numbers are inconsistent across files
  (spec §2.1). Never join on `referenceNumber`.
- **D2.2 — Currency null ⇒ CAD** (CanadaBuys docs). Non-CAD rows are flagged, not converted (no FX
  table in scope); value kept as reported with a `confidence_flag`.
- **D2.3 — Amendment handling.** Purely-administrative amendments (`amendmentType` indicating a
  non-financial/admin update) are dropped from turnover/concentration counting so they don't
  inflate award counts. The base award (amendment 000) original value is preserved separately
  (`original_value_cad`) because historical rows overwrote it with later amendment values.
- **D2.4 — Procedure & instrument are rule-based enums**, never AI: `procedure_class ∈
  {open_competitive, selective, ACAN, sole_source}`, `instrument_class ∈ {contract,
  standing_offer, call_up}` (spec §2.3, FR3).
- **D2.5 — Value conflicts surfaced, never silently resolved.** When proactive-disclosure value
  and CanadaBuys award value disagree for the same solicitation, both are kept and a
  `value_conflict` flag is set; "original value" prefers the base-award amount (spec §2.3, NFR).

---

## Milestone 3 — Entity resolution (the showcase / hardest problem)

**Goal:** Collapse vendor & department name variants to canonical entities; measure accuracy.

**Decisions**

- **D3.1 — Deterministic core, optional LLM.** Pipeline: name cleaning (suffix strip, casefold,
  punctuation/whitespace normalize) → blocking → `rapidfuzz` fuzzy clustering → adjudication of
  *only* the ambiguous middle band → manual M&A crosswalk for top-N vendors. The adjudicator is a
  pluggable interface: the default is deterministic (rule-based) so the system runs with **no API
  key**; an LLM adjudicator can be dropped in. Spec §2.4 delegates only ambiguous-pair adjudication
  to AI.
- **D3.2 — Conservative on merges (NFR4).** Three bands by similarity score: `>= high` auto-merge;
  `< low` keep separate; the middle band goes to the adjudicator and, if still unsure, to a
  `needs_review` bucket (kept separate, i.e. *not* merged). Default-to-not-merge.
- **D3.3 — Turnover cross-pressure made visible.** Because not-merging can *manufacture* phantom
  turnover, unresolved near-duplicate pairs that affect a market's winner set are surfaced to the
  user as "possible same vendor," not silently treated as distinct winners (spec §2.4).
- **D3.4 — Accuracy is measured.** A labelled pair set lives in the repo; a test computes
  entity-resolution **precision/recall** and asserts **precision ≥ 0.95** (false merges corrupt
  both pillars; spec §2.4 target).

---

## Milestone 4 — Signals: concentration, turnover, contestability, verdict

**Goal:** Per (commodity × buyer) metrics and the enterable/walled/ambiguous verdict.

**Decisions**

- **D4.1 — Concentration shortlists, never decides.** `top1_share` is the headline metric, `hhi`
  secondary (spec decision log). High concentration is a *shortlisting* condition only and is
  **never** labelled "beatable" on its own (FR4).
- **D4.2 — Turnover is first-class.** Metrics: `distinct_winners`, `lead_changes` (times the
  cumulative-value leader changed, in award-date order), `last_new_entrant_date` /
  `years_since_new_entrant`. Suppressed below `MIN_AWARDS_FOR_TURNOVER` (default 5) — you cannot
  read dynamism off a handful of awards (FR7).
- **D4.3 — Transparent contestability score (0–100).** A documented weighted blend of openness,
  absence of lock-in, and turnover. It does **not** reward low concentration into a "beatable"
  label; it ranks shortlisted (concentrated) markets by how enterable they look. Weights are
  constants in `signals.py`, fully re-derivable (NFR3).
- **D4.4 — Verdict logic (FR5), the central rule:**
  - `insufficient_data` if `n_awards < MIN_AWARDS`.
  - `walled` if lock-in present (standing offer / call-up share high) **or** procedure is
    predominantly non-open (sole_source / ACAN).
  - For concentrated + open + no-lock-in markets: `enterable` **iff** turnover is present
    (≥2 distinct winners **and** ≥1 lead change); otherwise **`ambiguous`** (high concentration,
    open procedure, near-zero turnover — "thin field or strong incumbent, can't tell").
  - Non-concentrated markets → `enterable` (no entrenched incumbent), de-prioritised in ranking.
  - **The hazard from the spec is encoded directly: high concentration + open + zero turnover ⇒
    `ambiguous`, never `enterable`.**

---

## Milestone 5 — Store & serve

**Goal:** DuckDB tables + Streamlit board with drill-down, provenance, ambiguity note, OPO prior.

**Decisions**

- **D5.1 — Two tables:** `awards` (canonical per-award) and `markets` (aggregated metrics + verdict).
  Market metrics are always re-derivable from `awards` (NFR3).
- **D5.2 — Provenance is mandatory (NFR1).** Every market row carries the list of contributing
  `solicitation_number`s; the UI drill-down shows the underlying award records and their source.
- **D5.3 — OPO single-bid prior is labelled context, never a per-record value** (~29% open / ~35%
  limited still drew one bid). Shown in the UI as the reason "open ≠ contested" (FR6).

---

## Milestone 6 — Tests, README, walkthrough

**Goal:** Someone else can run it; every tradeoff is explainable.

**Decisions**

- **D6.1 — Golden verdict cases.** `tests/test_verdict_cases.py` constructs one market for each of
  enterable / walled / ambiguous / insufficient_data and asserts the verdict — the demo's
  load-bearing behaviour.
- **D6.2 — Hand-verification test.** A test recomputes concentration & turnover for one market by
  hand and asserts the pipeline matches (spec §2.4 verification).

**Result:** Entity resolution measures **precision 1.000 / recall 0.867** on the 27-pair labelled
set (0 false merges), clearing the ≥0.95 precision gate. Full suite: **39 tests pass** (offline);
the live CKAN path is covered by 2 network-gated smoke tests.

---

## Milestone 7 — Bid-count signal (spec premise corrected mid-build)

**The discovery.** The spec's load-bearing premise — *"no federal bulk dataset exposes the number
of bids"* — was verified against the live data during ingestion and found to be **only true
historically**. TBS Proactive Disclosure's DataStore ("Contracts over $10,000", ~1.29M rows)
**has a `number_of_bids` column**: ~0% filled for 2017, **~90–100% for 2023+**, modal value `1`.
This was surfaced to the product owner, who directed that the field be made **first-class** with a
clear coverage caveat. (See memory `number-of-bids-field-exists`.)

**Decisions**

- **D7.1 — Mandate-aware coverage.** `number_of_bids` became a **permanent, mandatory** disclosure
  on **2023-06-30** (`config.BID_MANDATE_DATE`). Coverage and the measured single-bid rate are
  computed only over **post-mandate award events**; pre-mandate gaps are expected, not a fault.
- **D7.2 — Measured single-bid rate replaces the prior where coverage exists.** Per market we
  compute `single_bid_rate`, `bid_coverage`, `median_bids`, and a `bid_signal ∈
  {strong, weak, none}` (`strong` only with ≥ `min_covered_awards_for_bids` covered awards). The
  OPO rate stays as labelled context/fallback for thin-coverage markets (D5.3).
- **D7.3 — Bids resolve the directional ambiguity (the key win).** The spec's `ambiguous` case
  (concentrated + open + near-zero turnover — "thin field or strong incumbent, can't tell") is now
  *resolved* where bid coverage is strong: a **high** single-bid rate (incumbent wins unopposed) ⇒
  `enterable` (thin field you can enter); a **low** single-bid rate (incumbent beats many real
  rivals) ⇒ `walled` (genuinely strong incumbent). A mid-range rate, or thin/no coverage, **stays
  `ambiguous`** — we still never guess.
- **D7.4 — Kept out of the linear score on purpose.** `single_bid_rate` is a first-class displayed
  metric and a verdict driver, but is *not* folded into `contestability_score`, because its sign
  flips with concentration (high single-bid = enterable when concentrated, but ordinary in a
  healthy fragmented market). Putting it in a single linear score would be misleading; the verdict
  logic carries it correctly instead.
- **D7.5 — Scope boundary updated honestly.** We now *do* report the officially disclosed bid count
  where it exists, framed as the disclosed figure (with the OPO caveat that even an open single-bid
  process is not proof of wrongdoing). We still make **no** per-contract integrity claim and **no**
  overcharging claim.

---

## Milestone 8 — CanadaBuys contract-history spine (amendment-aware turnover)

**Goal.** Add the spec's "turnover backbone": amendment-aware award events from CanadaBuys contract
history, so award counts and turnover are correct on live data (the live PD path flattens
amendments).

**The blocking finding — the planned join is impossible.** The spec assumed a three-way join on
`solicitation_number`. Verified against live data: TBS Proactive Disclosure and CanadaBuys contract
history use **disjoint identifier systems** — PD keys are `C-YYYY-…-Q#-#####` / `P#######`;
contract history keys are departmental numbers like `CW2386284` / `W8482-242123`, and its
`solicitationNumber` is mostly blank. Measured intersection over ~6.8k CH keys × ~8.3k PD ids:
**0**. Contract history also has **no `number_of_bids` column**. So bid counts (PD-only) cannot be
joined onto the amendment-aware spine with published fields. We do not fabricate a key.

**Decisions**

- **D8.1 — Two complementary spines, deliberately not merged.** `--source live` (PD) carries the
  bid signal but flattens amendments; `--source contract_history` (CanadaBuys) is amendment-aware
  with procedure / instrument / GSIN / standardized supplier, but has no bid signal (falls back to
  the turnover/procedure/instrument verdict logic — the spec's original design). The user picks the
  lens; the impossibility of a key join is documented, not papered over.
- **D8.2 — Amendment logic activates on this spine.** Contract history populates
  `amendmentNumber`/`amendmentType`, so the (previously dormant on live) `clean.py` amendment logic
  fires: on FY2024-25, 2,919 of 6,320 rows are amendments (99 admin) → **3,401 real base award
  events**, not 6,320. This is the correctness fix the spine was added for.
- **D8.3 — Vendor name prefers the government-standardized field.** `supplierStandardizedName`
  (~20% filled) → legal → operating name. The standardized name *improves* entity resolution where
  present.
- **D8.4 — Contract identity = procurement number.** Used as `solicitation_number` because it is
  stable across a contract's amendment rows (the actual `solicitationNumber` field is mostly blank),
  so amendments group with their base award.
- **D8.5 — Empty-GSIN guard.** Rows with a blank GSIN are not a commodity market and are skipped in
  `compute_markets` (otherwise they lump into one giant pseudo-market on live data with missing
  coding). Synthetic data is unaffected.
- **D8.6 — File host needs a User-Agent.** The CanadaBuys file server returns 403 to the default
  agent; downloads send a browser-style UA.

**Result:** contract-history build runs end-to-end on real FY data (6,320 rows → 99 markets,
amendment-correct). Full suite **42 tests pass** (3 network-gated). Wiring the bid signal onto this
spine would require a probabilistic vendor+buyer+date+amount match — explicitly out of scope.
