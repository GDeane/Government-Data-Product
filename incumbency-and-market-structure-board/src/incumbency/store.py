"""DuckDB persistence (D5.1). Two tables: `awards` (canonical per-award, the source of
truth) and `markets` (aggregated metrics + verdict, always re-derivable from `awards`).

List/dict columns (confidence_flags, procedure_mix, provenance, …) are serialized to JSON
strings so the store stays a single portable file with no schema gymnastics; readers parse
them back. Date columns are stored as ISO strings for the same portability."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Union

import duckdb
import pandas as pd

from .config import DUCKDB_PATH

# Columns whose values are Python lists/dicts and must be JSON-encoded for storage.
_JSON_COLS = {
    "confidence_flags", "procedure_mix", "instrument_mix", "confounders",
    "possible_same_vendor", "solicitation_numbers",
}


def _encode(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if col in _JSON_COLS:
            out[col] = out[col].apply(lambda v: json.dumps(v, default=str))
        elif out[col].map(lambda v: isinstance(v, date)).any():
            out[col] = out[col].apply(lambda v: v.isoformat() if isinstance(v, date) else v)
    return out


def _decode(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if col in _JSON_COLS:
            out[col] = out[col].apply(lambda v: json.loads(v) if isinstance(v, str) and v else v)
    return out


def save(awards: pd.DataFrame, markets: pd.DataFrame,
         path: Union[str, Path] = DUCKDB_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    awards_enc = _encode(awards)
    markets_enc = _encode(markets)
    con = duckdb.connect(str(path))
    try:
        con.register("awards_df", awards_enc)
        con.register("markets_df", markets_enc)
        con.execute("DROP TABLE IF EXISTS awards")
        con.execute("DROP TABLE IF EXISTS markets")
        con.execute("CREATE TABLE awards AS SELECT * FROM awards_df")
        con.execute("CREATE TABLE markets AS SELECT * FROM markets_df")
    finally:
        con.close()


def load_markets(path: Union[str, Path] = DUCKDB_PATH) -> pd.DataFrame:
    con = duckdb.connect(str(path), read_only=True)
    try:
        df = con.execute("SELECT * FROM markets").df()
    finally:
        con.close()
    return _decode(df)


def load_awards(path: Union[str, Path] = DUCKDB_PATH) -> pd.DataFrame:
    con = duckdb.connect(str(path), read_only=True)
    try:
        df = con.execute("SELECT * FROM awards").df()
    finally:
        con.close()
    return _decode(df)


def awards_for_solicitations(solicitation_numbers, path: Union[str, Path] = DUCKDB_PATH
                             ) -> pd.DataFrame:
    """Provenance lookup (NFR1): fetch the underlying award records for a market's
    solicitation numbers so the UI drill-down can show traceable source rows."""
    if not solicitation_numbers:
        return pd.DataFrame()
    con = duckdb.connect(str(path), read_only=True)
    try:
        df = con.execute(
            "SELECT * FROM awards WHERE solicitation_number IN "
            f"({','.join(['?'] * len(solicitation_numbers))})",
            list(solicitation_numbers),
        ).df()
    finally:
        con.close()
    return _decode(df)
