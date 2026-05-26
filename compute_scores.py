"""
Compute the two composite scores per (gemeente, jaar):

    - Dutch Language Pressure Score
    - Educational Strain Score

Both follow the same recipe:
    1. Collect the component raw indicators for the year.
    2. Optionally cap a value (e.g. enrollment rate at 100).
    3. Multiply by `sign` (-1 reverses the indicator so that "high raw"
       still maps to "low score" — used for enrollment rate).
    4. Standardise (z-score) within the year, across municipalities.
    5. Average the standardised components.

A municipality whose components are all NaN for a given year receives NaN
for that score (no zero-imputation, no silent drop).

Years are discovered dynamically from the input data — nothing is hardcoded.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import (
    EDUCATIONAL_OUTCOME_COMPONENTS,
    LANGUAGE_PRESSURE_COMPONENTS,
)


# ---------------------------------------------------------------------------
# Derived helper indicators
# ---------------------------------------------------------------------------

def derive_helper_indicators(long_df: pd.DataFrame) -> pd.DataFrame:
    """
    Append derived indicators that are computed from the raw ones.

    Currently only one is needed:
        enrollment_rate_avg = mean(enrollment_rate_primary,
                                   enrollment_rate_secondary)

    The mean is taken per (gemeente, jaar) and skips NaN — so if only one
    of the two enrollment rates is reported, the average equals that value.
    If both are missing, the result is NaN.

    Parameters
    ----------
    long_df : pd.DataFrame
        Tidy long-format data (output of data_loader.load_long_format).

    Returns
    -------
    pd.DataFrame
        The same long-format DataFrame with extra rows for the derived
        indicator(s).
    """
    # Wide pivot for the two enrollment columns we need to average.
    wide = long_df.pivot_table(
        index=["gemeente", "provincie", "jaar"],
        columns="indicator",
        values="waarde",
        aggfunc="first",
    ).reset_index()

    # Average row-wise; NaN-skipping mean (np.nanmean if both present, else
    # the single non-NaN value, else NaN).
    enroll_cols = [c for c in ("enrollment_rate_primary",
                               "enrollment_rate_secondary") if c in wide.columns]
    if not enroll_cols:
        return long_df

    wide["enrollment_rate_avg"] = wide[enroll_cols].mean(axis=1, skipna=True)

    derived = wide[["gemeente", "provincie", "jaar",
                    "enrollment_rate_avg"]].copy()
    derived = derived.rename(columns={"enrollment_rate_avg": "waarde"})
    derived["indicator"] = "enrollment_rate_avg"
    derived = derived[["gemeente", "provincie", "indicator", "jaar", "waarde"]]

    return pd.concat([long_df, derived], ignore_index=True)


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def _zscore(series: pd.Series) -> pd.Series:
    """
    Z-score normalise a series, skipping NaN.

    Returns a series of the same shape; NaN stays NaN.
    If the series has zero variance, returns zeros (so the component does
    not contribute spuriously to the average).
    """
    mean = series.mean(skipna=True)
    std = series.std(skipna=True, ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(np.where(series.isna(), np.nan, 0.0), index=series.index)
    return (series - mean) / std


def _compute_one_score(
    wide_year: pd.DataFrame,
    components: list[dict],
) -> pd.Series:
    """
    Compute a single composite score for a single year.

    Parameters
    ----------
    wide_year : pd.DataFrame
        One row per gemeente, columns include every component indicator key.
    components : list of dict
        Each dict has keys 'key', 'sign', 'cap' (see config.py).

    Returns
    -------
    pd.Series
        Composite score per gemeente (NaN if all components missing).
    """
    standardised_cols = []

    for comp in components:
        key = comp["key"]
        sign = comp["sign"]
        cap = comp["cap"]

        if key not in wide_year.columns:
            # Component absent for this year entirely — skip silently.
            continue

        # Step 1: optional capping (e.g. enrollment rate at 100).
        raw = wide_year[key].astype(float)
        if cap is not None:
            raw = raw.clip(upper=cap)

        # Step 2: sign flip (-1 reverses for "lower is worse" indicators
        # like enrollment rate).
        oriented = raw * sign

        # Step 3: z-score within this year.
        standardised_cols.append(_zscore(oriented))

    if not standardised_cols:
        return pd.Series(np.nan, index=wide_year.index)

    # Stack into a DataFrame so we can take a row-wise NaN-skipping mean.
    stacked = pd.concat(standardised_cols, axis=1)

    # Require at least one non-NaN component per row; otherwise NaN.
    composite = stacked.mean(axis=1, skipna=True)
    composite[stacked.isna().all(axis=1)] = np.nan

    return composite


def compute_scores(long_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute Dutch Language Pressure and Educational Strain scores per
    (gemeente, jaar), looping dynamically over every year present in the
    input.

    Parameters
    ----------
    long_df : pd.DataFrame
        Tidy long-format data with at least the columns gemeente, provincie,
        indicator, jaar, waarde. Derived helper indicators are added inside.

    Returns
    -------
    pd.DataFrame
        Columns:
            gemeente, provincie, jaar,
            language_pressure_score, educational_outcome_score,
            plus every raw component indicator as its own column
            (handy for tooltips and Tab 5).
    """
    enriched = derive_helper_indicators(long_df)

    # Wide pivot: one row per (gemeente, provincie, jaar), one column per
    # indicator. This is the natural shape for per-year score computation.
    wide = enriched.pivot_table(
        index=["gemeente", "provincie", "jaar"],
        columns="indicator",
        values="waarde",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None  # drop the 'indicator' axis-name leftover

    out_chunks = []
    # Loop year by year — scores are normalised within each year separately.
    for year, year_df in wide.groupby("jaar"):
        year_df = year_df.copy()
        year_df["language_pressure_score"] = _compute_one_score(
            year_df, LANGUAGE_PRESSURE_COMPONENTS
        ).values
        year_df["educational_outcome_score"] = _compute_one_score(
            year_df, EDUCATIONAL_OUTCOME_COMPONENTS
        ).values
        out_chunks.append(year_df)

    scored = pd.concat(out_chunks, ignore_index=True)
    return scored


# ---------------------------------------------------------------------------
# OLS residuals (used in Tab 4)
# ---------------------------------------------------------------------------

def complete_score_years(
    long_df: pd.DataFrame,
    components: list[dict],
) -> list[int]:
    """
    Return the years for which *every* component of a composite score has
    at least one non-NaN observation.

    A year in which one of the components is *entirely missing* (e.g. 2025
    where 'newcomers_per_1000_adults' has 0 observations) would produce a
    score whose composition differs from previous years. We exclude those
    years from score-based charts to avoid misleading dips.

    Parameters
    ----------
    long_df : pd.DataFrame
        Tidy long-format data (after derive_helper_indicators).
    components : list of dict
        Component specs (LANGUAGE_PRESSURE_COMPONENTS or
        EDUCATIONAL_OUTCOME_COMPONENTS).

    Returns
    -------
    list of int
        Sorted years where the composite score is fully observable.
    """
    needed_keys = [c["key"] for c in components]
    sub = long_df[long_df["indicator"].isin(needed_keys)]
    counts = (
        sub.dropna(subset=["waarde"])
           .groupby(["jaar", "indicator"]).size()
           .unstack(fill_value=0)
    )
    # A year qualifies if every needed component has at least one obs.
    keep = counts.reindex(columns=needed_keys, fill_value=0).gt(0).all(axis=1)
    return sorted(keep[keep].index.astype(int).tolist())


def filter_scored_to_complete_years(
    scored: pd.DataFrame,
    long_df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[int]]:
    """
    Drop rows of `scored` whose year would yield an incomplete composite
    score for EITHER language pressure OR educational outcome.

    Returns
    -------
    (pd.DataFrame, list[int])
        Filtered scored DataFrame, and the sorted list of excluded years
        (handy for showing a caption to the user).
    """
    enriched = derive_helper_indicators(long_df)
    lp_years = set(complete_score_years(
        enriched, LANGUAGE_PRESSURE_COMPONENTS))
    eo_years = set(complete_score_years(
        enriched, EDUCATIONAL_OUTCOME_COMPONENTS))
    keep_years = sorted(lp_years & eo_years)
    excluded = sorted(set(scored["jaar"].unique()) - set(keep_years))
    return scored[scored["jaar"].isin(keep_years)].copy(), excluded


def ols_residuals_per_year(scored: pd.DataFrame) -> pd.DataFrame:
    """
    For every year, fit a simple OLS regression
        educational_outcome_score = a + b * language_pressure_score
    and return the residual per municipality.

    The residual answers: "Given this municipality's language pressure,
    is its educational outcome better or worse than expected?"

    Positive residual  -> WORSE than expected (higher outcome-pressure score
                          than the regression predicts).
    Negative residual  -> BETTER than expected.

    Parameters
    ----------
    scored : pd.DataFrame
        Output of compute_scores.

    Returns
    -------
    pd.DataFrame
        Columns: gemeente, provincie, jaar, residual.
    """
    rows = []
    for year, year_df in scored.groupby("jaar"):
        sub = year_df.dropna(
            subset=["language_pressure_score", "educational_outcome_score"]
        )
        if len(sub) < 3:
            continue

        x = sub["language_pressure_score"].values
        y = sub["educational_outcome_score"].values
        # 1st-degree polyfit = simple linear regression.
        slope, intercept = np.polyfit(x, y, deg=1)
        predicted = intercept + slope * x
        residual = y - predicted

        chunk = sub[["gemeente", "provincie", "jaar"]].copy()
        chunk["residual"] = residual
        rows.append(chunk)

    if not rows:
        return pd.DataFrame(columns=["gemeente", "provincie", "jaar", "residual"])
    return pd.concat(rows, ignore_index=True)


def rolling_average(scored: pd.DataFrame,
                    score_col: str,
                    window: int = 3) -> pd.DataFrame:
    """
    Add a rolling-average column (per municipality, ordered by year).

    Used in Tab 4 to smooth noise in score trajectories.

    Parameters
    ----------
    scored : pd.DataFrame
        Output of compute_scores.
    score_col : str
        Either 'language_pressure_score' or 'educational_outcome_score'.
    window : int
        Rolling window size, in years.

    Returns
    -------
    pd.DataFrame
        Same shape as input, with extra column f"{score_col}_rolling{window}".
    """
    out = scored.sort_values(["gemeente", "jaar"]).copy()
    new_col = f"{score_col}_rolling{window}"
    out[new_col] = (
        out.groupby("gemeente")[score_col]
           .transform(lambda s: s.rolling(window, min_periods=1).mean())
    )
    return out


def year_over_year_delta(scored: pd.DataFrame, score_col: str) -> pd.DataFrame:
    """
    Add a year-over-year delta column (per municipality).

    Used in Tab 4 to show how much a score moved from one year to the next.
    """
    out = scored.sort_values(["gemeente", "jaar"]).copy()
    new_col = f"{score_col}_delta"
    out[new_col] = out.groupby("gemeente")[score_col].diff()
    return out
