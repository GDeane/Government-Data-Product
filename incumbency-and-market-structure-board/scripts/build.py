#!/usr/bin/env python3
"""Build the market-structure board into DuckDB.

Usage:
    python scripts/build.py                       # synthetic fixtures (default, offline)
    python scripts/build.py --source synthetic
    python scripts/build.py --source live --limit 8000          # CKAN, TBS PD spine (bids)
    python scripts/build.py --source contract_history --years 2024-2025 2023-2024
                                                  # CanadaBuys amendment-aware turnover spine

Two live spines, deliberately not joined (their identifiers do not overlap — verified):
  * `live`             — TBS Proactive Disclosure: carries `number_of_bids` (the competition
                         signal), but flattens amendments.
  * `contract_history` — CanadaBuys contract history: amendment-aware award events, procedure,
                         instrument, standardized supplier — but no bid counts.

Writes data/market_board.duckdb with `awards` and `markets` tables, then prints a summary.
The synthetic path is fully offline and reproducible (D0.1); live paths hit the public CKAN
API (read-only, no key)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `incumbency` importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from incumbency import config, pipeline, store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the Incumbency & Market-Structure Board")
    ap.add_argument("--source", choices=["synthetic", "live", "contract_history"],
                    default="synthetic")
    ap.add_argument("--limit", type=int, default=8000,
                    help="max rows to pull from the live CKAN DataStore (live source)")
    ap.add_argument("--years", nargs="+", default=["2024-2025"],
                    help="fiscal years for the contract_history source, e.g. 2024-2025")
    ap.add_argument("--db", default=str(config.DUCKDB_PATH), help="output DuckDB path")
    args = ap.parse_args()

    config.ensure_dirs()

    if args.source == "synthetic":
        from incumbency import fixtures
        print("Building from synthetic fixtures (offline, deterministic)…")
        raw = fixtures.generate_raw_awards()
    elif args.source == "live":
        from incumbency import ingest
        print(f"Fetching up to {args.limit} rows from TBS Proactive Disclosure via CKAN…")
        raw = ingest.fetch_proactive_disclosure(max_rows=args.limit)
        print(f"  pulled {len(raw)} raw rows (bid-count signal available)")
    else:  # contract_history
        from incumbency import ingest
        print(f"Downloading CanadaBuys contract history for {args.years} via CKAN…")
        raw = ingest.fetch_contract_history(fiscal_years=args.years)
        print(f"  pulled {len(raw)} raw rows (amendment-aware; no bid counts)")

    result = pipeline.run_pipeline(raw)
    store.save(result.awards, result.markets, args.db)

    m = result.markets
    print(f"\nWrote {len(result.awards)} awards and {len(m)} markets to {args.db}")
    if not m.empty:
        counts = m["verdict"].value_counts().to_dict()
        print("Verdicts:", ", ".join(f"{k}={v}" for k, v in counts.items()))
        nr = len(result.vendor_resolution.needs_review_pairs)
        print(f"Vendor entities: {m['top1_vendor'].nunique()} distinct top-1 winners; "
              f"{nr} pair(s) flagged for review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
