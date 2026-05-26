"""
Rule-based, deterministic per-municipality summary.

For a chosen (gemeente, year), gathers a small set of facts from the
scored DataFrame:

  - position of both composite scores in the Flemish distribution (z + percentile)
  - the component indicator that drives each score most strongly
  - linear trend over the observed years (slope of each score on year)
  - OLS residual against the Flanders baseline (better / worse than expected)

and assembles them into a short English narrative (~150 words) using
human-written templates. No machine-learning, no API calls — the output
is fully reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import (
    EDUCATIONAL_OUTCOME_COMPONENTS,
    INDICATOR_DISPLAY,
    LANGUAGE_PRESSURE_COMPONENTS,
    STUDENT_CITIES,
)


@dataclass
class ScoreFacts:
    """All the deterministic facts we need to talk about ONE score."""
    score_label: str          # e.g. "Dutch Language Pressure"
    value: float              # current z-score
    percentile: float         # 0-100 (within all visible munis, current year)
    rank: int                 # 1 = highest
    total: int                # total munis ranked
    trend_slope: float        # z per year (linear fit over observed years)
    trend_label: str          # "rising" / "falling" / "stable"
    driver_key: str | None    # indicator key that contributes most
    driver_z: float | None    # its z-value (within year)
    component_keys: list[str]
    sign_map: dict[str, int]  # key -> +1 / -1 contribution sign


# ---------------------------------------------------------------------------
# Fact extraction
# ---------------------------------------------------------------------------

def _percentile_rank(series: pd.Series, value: float) -> float:
    """Return the percentile (0-100) of `value` within `series`."""
    s = series.dropna()
    if len(s) == 0:
        return float("nan")
    return float((s <= value).sum() / len(s) * 100)


def _trend_label(slope: float) -> str:
    """Translate a slope (z-units per year) into a human label."""
    if slope > 0.05:
        return "rising"
    if slope < -0.05:
        return "falling"
    return "stable"


def _zscore_within_year(series: pd.Series) -> pd.Series:
    mean = series.mean(skipna=True)
    std = series.std(skipna=True, ddof=0)
    if std in (0, np.nan) or pd.isna(std):
        return pd.Series(np.nan, index=series.index)
    return (series - mean) / std


def _collect_score_facts(
    scored: pd.DataFrame,
    gemeente: str,
    year: int,
    score_col: str,
    score_label: str,
    components: list[dict],
) -> ScoreFacts:
    """Gather all the per-score facts for `gemeente` in `year`."""
    # Position within the current year across all visible municipalities.
    year_slice = scored[scored["jaar"] == year]
    value = float(year_slice.loc[year_slice["gemeente"] == gemeente,
                                 score_col].iloc[0])
    pct = _percentile_rank(year_slice[score_col], value)
    ranked = year_slice.sort_values(score_col, ascending=False).reset_index(drop=True)
    rank = int(ranked.index[ranked["gemeente"] == gemeente][0]) + 1
    total = len(year_slice[score_col].dropna())

    # Linear trend over all observed years for THIS municipality.
    gem_hist = (scored[scored["gemeente"] == gemeente]
                .dropna(subset=[score_col])
                .sort_values("jaar"))
    if len(gem_hist) >= 3:
        slope, _ = np.polyfit(gem_hist["jaar"].values,
                              gem_hist[score_col].values, deg=1)
    else:
        slope = 0.0
    trend = _trend_label(float(slope))

    # Which component drives the score most? Compute z within year for
    # every component, oriented by its sign, and pick the largest.
    driver_key: str | None = None
    driver_z: float | None = None
    biggest = -float("inf")
    sign_map = {c["key"]: c["sign"] for c in components}
    for comp in components:
        key = comp["key"]
        sign = comp["sign"]
        if key not in scored.columns:
            continue
        # cap-then-orient before z-scoring, to match compute_scores.py.
        col = year_slice[key].astype(float)
        if comp.get("cap") is not None:
            col = col.clip(upper=comp["cap"])
        oriented = col * sign
        zcol = _zscore_within_year(oriented)
        gem_z = zcol.loc[year_slice["gemeente"] == gemeente]
        if gem_z.empty:
            continue
        z_val = float(gem_z.iloc[0])
        if pd.isna(z_val):
            continue
        if z_val > biggest:
            biggest = z_val
            driver_key = key
            driver_z = z_val

    return ScoreFacts(
        score_label=score_label,
        value=value,
        percentile=pct,
        rank=rank,
        total=total,
        trend_slope=float(slope),
        trend_label=trend,
        driver_key=driver_key,
        driver_z=driver_z,
        component_keys=[c["key"] for c in components],
        sign_map=sign_map,
    )


# ---------------------------------------------------------------------------
# Narrative templates
# ---------------------------------------------------------------------------

def _position_phrase(facts: ScoreFacts) -> str:
    pct = facts.percentile
    if pct >= 90:
        return f"sits in the **top decile** ({facts.score_label}: {facts.value:+.2f}σ, rank {facts.rank}/{facts.total})"
    if pct >= 75:
        return f"sits in the **upper quartile** ({facts.score_label}: {facts.value:+.2f}σ, rank {facts.rank}/{facts.total})"
    if pct >= 25:
        return f"sits **near the Flemish average** ({facts.score_label}: {facts.value:+.2f}σ, rank {facts.rank}/{facts.total})"
    if pct >= 10:
        return f"sits in the **lower quartile** ({facts.score_label}: {facts.value:+.2f}σ, rank {facts.rank}/{facts.total})"
    return f"sits in the **bottom decile** ({facts.score_label}: {facts.value:+.2f}σ, rank {facts.rank}/{facts.total})"


def _trend_phrase(facts: ScoreFacts, years_span: int) -> str:
    direction = facts.trend_label
    total_drift = facts.trend_slope * years_span
    if direction == "stable":
        return f"has stayed essentially flat ({total_drift:+.2f}σ over the period)"
    return f"has been {direction} ({total_drift:+.2f}σ over the period)"


def _residual_phrase(residual: float | None) -> str:
    if residual is None or pd.isna(residual):
        return ""
    if residual <= -0.5:
        return (f"performs **clearly better than the Flanders regression "
                f"predicts** (residual {residual:+.2f}σ) — i.e. its "
                f"educational outcomes are stronger than the language "
                f"pressure alone would suggest")
    if residual >= 0.5:
        return (f"performs **clearly worse than the Flanders regression "
                f"predicts** (residual {residual:+.2f}σ) — i.e. its "
                f"educational outcomes are weaker than the language "
                f"pressure alone would suggest")
    return (f"sits **close to the regression line** (residual {residual:+.2f}σ) — "
            f"its educational outcomes are roughly in line with what its "
            f"language pressure would predict")


def _driver_phrase(facts: ScoreFacts) -> str:
    if facts.driver_key is None or facts.driver_z is None:
        return ""
    label = INDICATOR_DISPLAY.get(facts.driver_key, facts.driver_key)
    if facts.driver_z > 1.0:
        return f"The single biggest driver is **{label}** ({facts.driver_z:+.2f}σ)."
    if facts.driver_z < -1.0:
        return f"The strongest contributor (in reverse) is **{label}**."
    return f"The components contribute fairly evenly — no single dominant driver."


def _policy_phrase_language(lp: ScoreFacts, gemeente: str = "") -> str:
    """Policy advice focused on the Dutch language pressure side.

    `gemeente` is used to detect known student / university cities where
    the newcomers indicator partly captures international students and
    academic staff — a population that is NOT the policy target of
    NT2 / OKAN / civic-integration measures.
    """
    notes = []
    high = lp.percentile >= 75
    very_high = lp.percentile >= 90
    is_student_city = gemeente in STUDENT_CITIES
    newcomers_driven = (
        lp.driver_key == "newcomers_per_1000_adults"
        and lp.driver_z is not None
        and lp.driver_z > 1.0
    )

    if very_high:
        notes.append(
            "Language pressure sits in the **top decile** — sustained, "
            "structural investment in Dutch-language support is essential: "
            "Dutch-as-a-second-language (NT2) in classrooms, OKAN reception "
            "programmes for newcomer pupils, and parental Dutch courses to "
            "extend language exposure beyond school hours."
        )
    elif high:
        notes.append(
            "Language pressure is **above average**: keep NT2 capacity in "
            "primary and secondary schools well-staffed; invest in "
            "language-rich early-childhood services (kindergartens, "
            "Huizen van het Kind)."
        )
    else:
        notes.append(
            "Language pressure is **low to moderate**: focus on maintaining "
            "general language quality; no need for targeted NT2 expansion "
            "beyond the current baseline."
        )

    # Driver-specific add-ons.
    if newcomers_driven:
        notes.append(
            "The dominant driver is the **newcomers indicator** — i.e. "
            "today's adult inflow, tomorrow's pupil parents. **Anticipate** "
            "future classroom demand: secure school capacity 3-5 years "
            "ahead and strengthen integration trajectories for adult "
            "newcomers (Dutch courses, civic integration)."
        )
        # NB: the student-city caveat is emitted as a separate yellow
        # callout (see `student_city_caveat()` below), so it visually
        # stands out from the regular policy paragraph.
    elif lp.driver_key in ("pct_nl_primary", "pct_nl_secondary") and lp.driver_z and lp.driver_z > 1.0:
        notes.append(
            "The dominant driver is the **share of pupils not speaking "
            "Dutch at home**, indicating a structural home-language "
            "context. Combine in-school NT2 with **outreach to families** "
            "(multilingual communication, parental information evenings)."
        )

    if lp.trend_label == "rising":
        notes.append(
            "**Trend is rising** — scale up rather than maintain: the "
            "current intervention level will be insufficient if the "
            "trajectory continues."
        )
    elif lp.trend_label == "falling":
        notes.append(
            "**Trend is falling** — current measures are bearing fruit; "
            "avoid premature withdrawal of resources."
        )

    return " ".join(notes)


def _policy_phrase_strain(es: ScoreFacts) -> str:
    """Policy advice focused on the educational strain side."""
    notes = []
    high = es.percentile >= 75
    very_high = es.percentile >= 90

    if very_high:
        notes.append(
            "Educational strain is in the **top decile** — outcomes are "
            "structurally weak. Coordinated action is needed across the "
            "pupil's full trajectory."
        )
    elif high:
        notes.append(
            "Educational strain is **above average** — targeted "
            "interventions on the weakest component are warranted."
        )
    else:
        notes.append(
            "Educational strain is **low to moderate** — current outcome "
            "indicators are healthy; the focus can stay on quality and "
            "equity rather than crisis response."
        )

    # Driver-specific concrete suggestions.
    if es.driver_key == "pct_delay_secondary" and es.driver_z and es.driver_z > 1.0:
        notes.append(
            "The dominant driver is **secondary-school delay (2+ years)** "
            "— prioritise **early detection** in primary, individual "
            "remediation plans in the first secondary years and bridge "
            "classes for pupils at risk."
        )
    elif es.driver_key == "pct_early_school_leavers" and es.driver_z and es.driver_z > 1.0:
        notes.append(
            "The dominant driver is **early school leaving** — invest in "
            "**dropout prevention** (mentors, attendance monitoring), "
            "strengthen dual-learning / vocational pathways, and improve "
            "links with youth-welfare services."
        )
    elif es.driver_key == "enrollment_rate_avg" and es.driver_z and es.driver_z > 1.0:
        notes.append(
            "The dominant driver is **low enrollment** — review "
            "**accessibility** (school transport, fees), outreach to "
            "under-enrolled groups, and capacity bottlenecks in "
            "kindergartens / first-year secondary."
        )

    if es.trend_label == "rising":
        notes.append(
            "**Trend is rising** — current measures are not yet bending "
            "the curve; consider a structural review rather than further "
            "incremental adjustments."
        )
    elif es.trend_label == "falling":
        notes.append(
            "**Trend is falling** — outcomes are improving; protect the "
            "current effort and document what is working."
        )

    return " ".join(notes)


def _policy_phrase_combined(
    lp: ScoreFacts, es: ScoreFacts, residual: float | None
) -> str:
    """Overarching, integrated policy lens combining both scores + residual."""
    notes = []

    # Quadrant logic on (language pressure, strain). Thresholds match
    # the position-phrase elsewhere (75th = upper quartile, 25th = lower
    # quartile) so the narrative stays internally consistent.
    lp_high = lp.percentile >= 75
    es_high = es.percentile >= 75
    lp_low = lp.percentile <= 25
    es_low = es.percentile <= 25

    if lp_high and es_high:
        notes.append(
            "Both pressure axes are elevated. This is the **'high-need' "
            "profile**: language interventions and outcome interventions "
            "must run in parallel and be coordinated — schools, the local "
            "social services and integration agencies should be aligned "
            "around the same pupil cohorts."
        )
    elif lp_high and es_low:
        notes.append(
            "**Decoupled profile**: high language pressure but contained "
            "outcomes. The local school system is currently absorbing the "
            "language load well — invest in **documenting and "
            "transferring** the practices that make this possible."
        )
    elif lp_low and es_high:
        notes.append(
            "**Decoupled profile**: outcomes are strained despite "
            "moderate language pressure. The drivers are likely "
            "**non-linguistic** — socio-economic, school capacity, "
            "mobility — and that is where the policy response should "
            "concentrate."
        )
    elif lp_low and es_low:
        notes.append(
            "Both axes are low: the municipality is in a **maintenance "
            "regime**. Continue monitoring; reallocate marginal capacity "
            "to municipalities under more acute pressure if shared "
            "regionally."
        )
    else:
        notes.append(
            "Position is mixed across the two axes — the per-score "
            "recommendations above are the most concrete starting point."
        )

    # Residual lens.
    if residual is not None and residual <= -0.5:
        notes.append(
            "The municipality **outperforms the Flemish regression line** "
            "(residual {:+.2f}σ). Local practice is doing more with the "
            "same language profile — share findings via provincial peer "
            "networks.".format(residual)
        )
    elif residual is not None and residual >= 0.5:
        notes.append(
            "The municipality **underperforms the Flemish regression "
            "line** (residual {:+.2f}σ). Outcomes lag what the language "
            "profile alone would predict — investigate non-language "
            "drivers (SES, school capacity, mobility, staffing) before "
            "scaling existing language responses.".format(residual)
        )

    # Trajectory.
    if lp.trend_label == "rising" and es.trend_label == "rising":
        notes.append(
            "Both pressures are trending **upward** — plan capacity for "
            "the next monitoring cycle now, do not wait for it to "
            "materialise."
        )
    elif lp.trend_label == "falling" and es.trend_label == "falling":
        notes.append(
            "Both pressures are trending **downward** — current trajectory "
            "is positive; protect resources from premature reallocation."
        )

    return " ".join(notes)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def student_city_caveat(lp: ScoreFacts, gemeente: str) -> str | None:
    """
    Return the student-city nuance text when applicable, else None.

    Triggers ONLY when:
      - the municipality is in the curated STUDENT_CITIES set, AND
      - the newcomers indicator is the dominant driver of its language
        pressure score (z > 1.0).

    The returned string is meant to be rendered as a separate yellow
    callout (st.warning), NOT inline in the policy paragraph.
    """
    is_student_city = gemeente in STUDENT_CITIES
    newcomers_driven = (
        lp.driver_key == "newcomers_per_1000_adults"
        and lp.driver_z is not None
        and lp.driver_z > 1.0
    )
    if not (is_student_city and newcomers_driven):
        return None
    return (
        f"Student city indicated, possible nuance: {gemeente} hosts a "
        "large academic population (international students, researchers, "
        "expat staff). A substantial share of the newcomers count likely "
        "reflects this **transient, highly-educated adult flow** rather "
        "than permanent settlers needing integration trajectories. Before "
        "scaling NT2/OKAN capacity, disaggregate the newcomer population: "
        "students and academic staff typically do not enrol children in "
        "local Flemish schools or seek civic-integration services to the "
        "same extent as permanent newcomers, so the operational classroom "
        "demand is likely lower than the headline figure suggests."
    )


def analyse_municipality(
    scored: pd.DataFrame,
    residuals: pd.DataFrame,
    gemeente: str,
    year: int,
) -> dict:
    """
    Build a short, deterministic analysis for one municipality / year.

    Returns
    -------
    dict
        {
          "markdown": str,            # the main narrative + policy advice
          "student_city_caveat": str | None,  # optional yellow callout
        }
    The caller renders the markdown via st.markdown and, if the caveat
    is non-None, follows it with st.warning(caveat).
    """
    if gemeente not in scored["gemeente"].unique():
        return {"markdown": f"_No data available for {gemeente}._",
                "student_city_caveat": None}
    year_obs = scored[(scored["gemeente"] == gemeente) &
                      (scored["jaar"] == year)]
    if year_obs.empty:
        return {"markdown": f"_No data available for {gemeente} in {year}._",
                "student_city_caveat": None}

    provincie = year_obs["provincie"].iloc[0]
    lp = _collect_score_facts(
        scored, gemeente, year,
        score_col="language_pressure_score",
        score_label="Dutch Language Pressure",
        components=LANGUAGE_PRESSURE_COMPONENTS,
    )
    es = _collect_score_facts(
        scored, gemeente, year,
        score_col="educational_outcome_score",
        score_label="Educational Strain",
        components=EDUCATIONAL_OUTCOME_COMPONENTS,
    )

    res_row = residuals[(residuals["gemeente"] == gemeente) &
                        (residuals["jaar"] == year)]
    residual = float(res_row["residual"].iloc[0]) if not res_row.empty else None

    years_observed = scored[scored["gemeente"] == gemeente]["jaar"].dropna()
    years_span = int(years_observed.max() - years_observed.min()) if len(years_observed) else 0

    parts = [
        f"### Auto-analysis — {gemeente} ({provincie}), {year}",
        f"On Dutch Language Pressure, **{gemeente}** {_position_phrase(lp)} "
        f"and the score {_trend_phrase(lp, years_span)}. "
        f"{_driver_phrase(lp)}",
        f"On Educational Strain, it {_position_phrase(es)} "
        f"and {_trend_phrase(es, years_span)}. "
        f"{_driver_phrase(es)}",
    ]
    rp = _residual_phrase(residual)
    if rp:
        parts.append(f"Relative to the Flemish regression line, {gemeente} {rp}.")

    parts.append("---")
    parts.append("#### 🗣️ Policy advice — Dutch Language Pressure")
    parts.append(_policy_phrase_language(lp, gemeente=gemeente))
    parts.append("#### 🎓 Policy advice — Educational Strain")
    parts.append(_policy_phrase_strain(es))
    parts.append("#### 🧭 Integrated policy lens")
    parts.append(_policy_phrase_combined(lp, es, residual))

    parts.append(
        "_This summary is generated from the data via fixed rules — "
        "no AI is involved. Numbers are the same as in the charts above; "
        "interpretation is conservative and meant as a starting point._"
    )
    return {
        "markdown": "\n\n".join(parts),
        "student_city_caveat": student_city_caveat(lp, gemeente),
    }
