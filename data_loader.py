"""
Load the raw provincies.incijfers.be wide-format Excel export and reshape it
into the tidy long-format DataFrame the rest of the dashboard expects:

    columns = [gemeente, provincie, indicator, jaar, waarde]

Design notes
------------
- Wide format has 2 header rows: indicator label (row 1) + year (row 2).
- Indicator labels appear ONCE at the LAST column of each 12-year block
  (cols 12, 24, 36, ... — a quirk of the provincies.incijfers.be export).
  We back-fill so every data column inherits the label of the block it
  belongs to (cols 1-12 -> first label, cols 13-24 -> second label, ...).
- Missing values are encoded as '-' in the source and are coerced to NaN.
  Literal zeros are preserved (per project decision).
- Bookkeeping rows ("Datum export", "Bron", "Niet te lokaliseren", ...) are
  dropped via config.HOUSEKEEPING_ROWS.
- Indicators that are not declared in config.INDICATOR_LABELS are silently
  ignored (forward-compatible with future Excel exports that add columns).
- Province is attached via config.PROVINCE_BY_MUNICIPALITY; municipalities
  not in the lookup are kept but provincie is set to NaN (so they remain
  visible in tables, just uncoloured).
"""

from __future__ import annotations

import pandas as pd

from config import (
    DATA_FILE,
    HOUSEKEEPING_ROWS,
    INDICATOR_LABELS,
    PROVINCE_BY_MUNICIPALITY,
)


# Reverse map: raw Excel label -> internal short indicator key.
_LABEL_TO_KEY: dict[str, str] = {label: key for key, label in INDICATOR_LABELS.items()}


def load_long_format(path=DATA_FILE) -> pd.DataFrame:
    """
    Read the raw Excel export and return a tidy long-format DataFrame.

    Parameters
    ----------
    path : pathlib.Path
        Location of the wide-format Excel file.

    Returns
    -------
    pandas.DataFrame
        Columns: gemeente (str), provincie (str | NaN), indicator (str,
        internal key), jaar (int), waarde (float | NaN).

    Notes
    -----
    - Only indicators declared in config.INDICATOR_LABELS are kept.
    - '-' is treated as NaN; literal 0 is kept as 0.
    - One row per (gemeente, indicator, jaar) — duplicates are not expected
      but if present the LAST one wins (Excel's natural ordering).
    """
    # Read the raw sheet with NO header so we can deal with the 2-row meta
    # information ourselves. Row 0 is the export title; row 1 the indicator
    # label (only at block start); row 2 the year; rows 3+ the data.
    raw = pd.read_excel(path, header=None)

    # Row 1 holds the indicator labels at the END of each 12-year block.
    # Back-fill so every column carries the label of the indicator block it
    # belongs to (NaN cells receive the next label to their right).
    indicator_row = raw.iloc[1].bfill()
    # Row 2 holds the year for each data column.
    year_row = raw.iloc[2]

    # Body: from row 3 onwards. Column 0 is the municipality name.
    body = raw.iloc[3:].reset_index(drop=True)
    body.columns = range(body.shape[1])

    # Strip whitespace from municipality names and drop housekeeping rows.
    body[0] = body[0].astype(str).str.strip()
    body = body[~body[0].isin(HOUSEKEEPING_ROWS)]
    body = body[body[0].notna() & (body[0] != "nan")]

    long_rows = []
    # Iterate data columns (skip column 0 = municipality name).
    for col in range(1, raw.shape[1]):
        raw_indicator_label = indicator_row.iloc[col]
        raw_year = year_row.iloc[col]

        # Skip columns whose indicator block isn't declared in config.
        indicator_key = _LABEL_TO_KEY.get(raw_indicator_label)
        if indicator_key is None:
            continue

        # Parse year robustly (Excel sometimes stores it as text).
        try:
            jaar = int(raw_year)
        except (TypeError, ValueError):
            continue

        # Build one slice (gemeente, waarde) for this (indicator, year) column.
        slice_df = pd.DataFrame({
            "gemeente": body[0].values,
            "indicator": indicator_key,
            "jaar": jaar,
            "waarde": body[col].values,
        })
        long_rows.append(slice_df)

    long_df = pd.concat(long_rows, ignore_index=True)

    # Coerce '-' (and other non-numeric strings) to NaN. pandas does this for
    # us via to_numeric with errors='coerce'.
    long_df["waarde"] = pd.to_numeric(long_df["waarde"], errors="coerce")

    # Attach provincie (left join; unmatched municipalities get NaN).
    long_df["provincie"] = long_df["gemeente"].map(PROVINCE_BY_MUNICIPALITY)

    # Reorder columns to match the spec.
    long_df = long_df[["gemeente", "provincie", "indicator", "jaar", "waarde"]]

    return long_df


def available_years(long_df: pd.DataFrame) -> list[int]:
    """Return a sorted list of all years present in the long-format data."""
    return sorted(long_df["jaar"].dropna().unique().astype(int).tolist())


def available_municipalities(long_df: pd.DataFrame) -> list[str]:
    """Return a sorted list of all municipalities in the long-format data."""
    return sorted(long_df["gemeente"].dropna().unique().tolist())
