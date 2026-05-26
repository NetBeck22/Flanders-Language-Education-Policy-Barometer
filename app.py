"""
Flanders Language & Education Policy Barometer
==============================================

A Streamlit dashboard that lets policy-makers and analysts explore the
relationship between language context and educational outcomes across
Flemish municipalities, 2014-2024.

Run locally with:

    pip install streamlit plotly pandas openpyxl scikit-learn
    streamlit run app.py

Layout
------
Sidebar:
  - province multiselect (filter)
  - municipality multiselect (highlight pattern — see below)
  - year slider (single year for cross-sectional tabs)
  - trend-method selector (Tab 4)

Tabs:
  1. Dutch Language Pressure  — distribution, ranking, evolution
  2. Educational Strain — same structure for the outcome score
  3. Core scatter        — both scores, animated over time
  4. Trend & deviation   — OLS residuals, smoothing, year-over-year delta
  5. Municipal detail    — raw indicators, radar, downloadable table

Highlight-pattern (key UX)
--------------------------
A single multiselect drives every chart: selected municipalities appear in
their full colour; everything else is drawn in light grey. The selection
persists in st.session_state, so switching tabs preserves focus.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import (
    FLEMISH_PROVINCES,
    GREY_COLOR,
    HIGHLIGHT_PALETTE,
    HIGHLIGHT_PALETTES,
    INDICATOR_DISPLAY,
    INDICATOR_DISPLAY_SCALE,
    INDICATOR_TOOLTIP,
    PROVINCE_PALETTE,
    PROVINCE_PALETTES,
    SCORE_CAVEAT,
    SCORE_DESCRIPTIONS,
    SCORE_LABELS,
)
from auto_analysis import analyse_municipality
from compute_scores import (
    compute_scores,
    derive_helper_indicators,
    filter_scored_to_complete_years,
    ols_residuals_per_year,
)
from data_loader import (
    available_municipalities,
    available_years,
    load_long_format,
)


# ---------------------------------------------------------------------------
# Cached loading (so re-renders don't re-read the Excel)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Loading data...")
def cached_long_format() -> pd.DataFrame:
    """Load the long-format DataFrame once per session."""
    return load_long_format()


@st.cache_data(show_spinner="Computing composite scores...")
def cached_scores(_long_df_hash: int, long_df: pd.DataFrame) -> pd.DataFrame:
    """Compute scores once per session. Hash arg forces re-cache on data change."""
    return compute_scores(long_df)


@st.cache_data
def cached_enriched(_h: int, long_df: pd.DataFrame) -> pd.DataFrame:
    """Long-format DataFrame with derived helper indicators appended."""
    return derive_helper_indicators(long_df)


# ---------------------------------------------------------------------------
# Highlight helpers
# ---------------------------------------------------------------------------

def color_for_row(
    gemeente: str,
    provincie: str,
    highlight: list[str],
    use_province_palette: bool = True,
) -> str:
    """
    Return the colour a marker should take given the current highlight.

    If the highlight list is non-empty:
        - selected municipalities -> province colour (or a default blue)
        - all others              -> light grey
    If the highlight list is empty:
        - everything gets its province colour (no greying)

    Parameters
    ----------
    gemeente : str
    provincie : str
    highlight : list of str
        Currently-selected municipalities (drives the focus + context view).
    use_province_palette : bool
        If False, return a single default blue for non-grey points.
    """
    if highlight and gemeente not in highlight:
        return GREY_COLOR
    if use_province_palette:
        return PROVINCE_PALETTE.get(provincie, "#1f77b4")
    return "#1f77b4"


def add_highlight_color_column(
    df: pd.DataFrame,
    highlight: list[str],
    use_province_palette: bool = True,
) -> pd.DataFrame:
    """Add a `_color` column to `df` based on the highlight rules."""
    df = df.copy()
    df["_color"] = [
        color_for_row(g, p, highlight, use_province_palette)
        for g, p in zip(df["gemeente"], df["provincie"])
    ]
    return df


# Dash-pattern cycles assigned within a province when multiple
# municipalities from that province are highlighted. Two cycles:
# - lines/curves (evolution chart) start at "solid"
# - vertical lines (distribution chart) start at "dash" — a vline that
#   is fully solid would visually merge with the KDE-curve filled area
_DASH_CYCLE_LINE = ["solid", "dash", "dot", "dashdot", "longdash", "longdashdot"]
_DASH_CYCLE_VLINE = ["dash", "dot", "dashdot", "longdash", "longdashdot", "solid"]


def municipality_dash_pattern(
    highlights: list[str],
    province_lookup: dict[str, str | None] | None = None,
    cycle: list[str] | None = None,
) -> dict[str, str]:
    """
    Return a `{gemeente: dash_pattern}` mapping so that two municipalities
    from the SAME province get visually distinguishable line patterns,
    while keeping the province colour intact.

    Sorted alphabetically within each province for determinism. Pass
    `cycle` to override the default ("solid"-first) sequence — useful
    for vertical lines where "solid" doesn't read as a deliberate dash.
    """
    if province_lookup is None:
        from config import PROVINCE_BY_MUNICIPALITY as _provinces
        province_lookup = _provinces
    if cycle is None:
        cycle = _DASH_CYCLE_LINE

    by_prov: dict[str | None, list[str]] = {}
    for gem in sorted(highlights):
        by_prov.setdefault(province_lookup.get(gem), []).append(gem)

    result: dict[str, str] = {}
    for _prov, gems in by_prov.items():
        for i, gem in enumerate(gems):
            result[gem] = cycle[i % len(cycle)]
    return result


def opacity_for(highlight: list[str], gemeente: str) -> float:
    """Lower opacity for context (non-selected) municipalities."""
    if not highlight:
        return 0.85
    return 0.95 if gemeente in highlight else 0.35


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

SCORE_HUMAN = {
    "language_pressure_score": "Dutch Language Pressure Score",
    "educational_outcome_score": "Educational Strain Score",
}


def build_histogram(
    scored: pd.DataFrame,
    score_col: str,
    year: int,
    highlight: list[str],
) -> go.Figure:
    """
    Animated distribution chart: one KDE curve per province, one frame
    per year, with Play / Pause and a year timeline.

    The initial frame is the LAST year in the data (2024 typically) so
    the chart opens on the most recent snapshot. The x-axis and y-axis
    ranges are FIXED across all frames so the curves don't jump or
    squish when the year changes — they just shift smoothly left/right
    and grow/shrink vertically.

    `year` and `highlight` are kept in the signature for call-site
    compatibility; they are no longer used inside (the year is encoded
    by the slider, and highlighted-municipality vlines are dropped in
    the animated version — the bar race and the evolution chart in the
    same tab already track specific municipalities).
    """
    from scipy.stats import gaussian_kde

    sub = scored.dropna(subset=[score_col]).copy()

    # Consistent province ordering across the dashboard.
    province_order = [p for p in FLEMISH_PROVINCES
                      if p in sub["provincie"].unique()]
    if "Brussel (gewest)" in sub["provincie"].unique():
        province_order.append("Brussel (gewest)")

    # One common x-grid spanning ALL years and provinces so the KDE
    # tails always land inside the same plot area.
    x_min, x_max = float(sub[score_col].min()), float(sub[score_col].max())
    margin = 0.1 * (x_max - x_min) if x_max > x_min else 1.0
    x_grid = np.linspace(x_min - margin, x_max + margin, 300)
    x_range = [x_min - margin, x_max + margin]

    years_sorted = sorted(sub["jaar"].dropna().unique().astype(int).tolist())
    if not years_sorted:
        return go.Figure()

    # Pre-compute (year -> [Scatter trace, ...]) so we can re-use the
    # trace objects in both the initial figure and the frame list.
    per_year_traces: dict[int, list[go.Scatter]] = {}
    max_density = 0.0
    for yr in years_sorted:
        traces = []
        year_sub = sub[sub["jaar"] == yr]
        for prov in province_order:
            values = year_sub.loc[
                year_sub["provincie"] == prov, score_col
            ].values
            if len(values) < 2 or np.ptp(values) == 0:
                # Empty placeholder trace keeps the trace count stable
                # across frames, which Plotly's animation expects.
                traces.append(go.Scatter(
                    x=[], y=[], mode="lines",
                    line=dict(color=PROVINCE_PALETTE.get(prov, "#888888"),
                              width=2.5),
                    name=prov,
                    showlegend=True,
                ))
                continue
            kde = gaussian_kde(values)
            density = kde(x_grid)
            max_density = max(max_density, float(density.max()))
            colour = PROVINCE_PALETTE.get(prov, "#888888")
            traces.append(go.Scatter(
                x=x_grid, y=density,
                mode="lines",
                line=dict(color=colour, width=2.5),
                name=f"{prov} (n={len(values)})",
                hovertemplate=(
                    f"<b>{prov}</b><br>"
                    + SCORE_HUMAN[score_col] + ": %{x:.2f}<br>"
                    "Density: %{y:.3f}<extra></extra>"
                ),
                fill="tozeroy",
                fillcolor=_rgba_from_hex(colour, alpha=0.10),
            ))
        per_year_traces[yr] = traces

    y_max = max_density * 1.10 if max_density > 0 else 1.0

    # ---- Per-frame vertical lines for highlighted municipalities ----
    # Each highlighted gemeente becomes ONE extra trace per frame, a
    # dashed vertical line from y=0 to y=y_max at the gemeente's score
    # for that year. Plotly's animation requires the trace count to be
    # identical across frames, so missing-data years still produce a
    # placeholder (empty) trace with the same name.
    #
    # Colour follows the SAME rule as the evolution chart in this tab:
    # the gemeente's province colour from PROVINCE_PALETTE, so a single
    # municipality keeps the same colour across the two views.
    hl_sorted = sorted(highlight) if highlight else []
    hl_colour: dict[str, str] = {}
    for gem in hl_sorted:
        prov_row = sub[sub["gemeente"] == gem]["provincie"]
        prov = prov_row.iloc[0] if not prov_row.empty else None
        hl_colour[gem] = PROVINCE_PALETTE.get(prov, "#1f77b4")
    # Two munis from the same province get distinguishable line dashes.
    # Vline cycle starts at "dash" (the conventional vertical-line look).
    dash_for_vline = municipality_dash_pattern(
        hl_sorted, cycle=_DASH_CYCLE_VLINE
    )
    score_label_str = SCORE_HUMAN[score_col]
    for yr in years_sorted:
        for gem in hl_sorted:
            row = sub[(sub["jaar"] == yr) & (sub["gemeente"] == gem)]
            colour = hl_colour[gem]
            dash = dash_for_vline.get(gem, "dash")
            if row.empty or pd.isna(row[score_col].iloc[0]):
                # Placeholder so frame trace counts stay stable.
                per_year_traces[yr].append(go.Scatter(
                    x=[None], y=[None], mode="lines",
                    line=dict(color=colour, width=2, dash=dash),
                    name=gem, showlegend=True, hoverinfo="skip",
                ))
                continue
            score_val = float(row[score_col].iloc[0])
            per_year_traces[yr].append(go.Scatter(
                x=[score_val, score_val], y=[0, y_max],
                mode="lines+text",
                line=dict(color=colour, width=2, dash=dash),
                text=["", gem],
                textposition="top center",
                textfont=dict(color=colour, size=11),
                name=gem,
                showlegend=True,
                hovertemplate=(
                    f"<b>{gem}</b><br>Year: {yr}<br>"
                    f"{score_label_str}: {score_val:.2f}<extra></extra>"
                ),
            ))

    # Initial frame = last year so the chart opens on the latest snapshot.
    initial_year = years_sorted[-1]
    initial_traces = per_year_traces[initial_year]

    frames = [
        go.Frame(data=per_year_traces[yr], name=str(yr))
        for yr in years_sorted
    ]

    fig = go.Figure(data=initial_traces, frames=frames)
    y_range = [0, y_max]

    fig.update_layout(
        # Centred title — avoids collision with the y-axis label on the
        # left edge of the chart.
        title=dict(
            text=(f"Distribution of {SCORE_HUMAN[score_col]} per province — "
                  "animated 2014-2024"),
            x=0.5, xanchor="center",
        ),
        # X-axis title is dropped: the chart title already names the
        # score and the timeline slider sits flush against the bottom of
        # the plot area.
        xaxis_title=None,
        yaxis_title="Density (KDE)",
        xaxis=dict(range=x_range, autorange=False),
        yaxis=dict(range=y_range, autorange=False),
        # Fixed figure height so the layout below the plot (timeline +
        # legend) has predictable absolute space.
        height=520,
        # Legend on the right, vertical — gets it completely out of the
        # way of the chart title (top) and the Play / Pause + slider
        # strip (bottom). Stacks 6 provinces cleanly.
        legend=dict(
            orientation="v", title="",
            x=1.02, xanchor="left",
            y=1.0, yanchor="top",
        ),
        hovermode="x unified",
        margin=dict(l=60, r=180, t=70, b=130),
        updatemenus=[dict(
            type="buttons", direction="left", showactive=False,
            x=0, xanchor="left", y=-0.10, yanchor="top",
            pad=dict(r=10, t=5),
            buttons=[
                dict(label="▶ Play", method="animate",
                     args=[None, {
                         "frame": {"duration": 800, "redraw": True},
                         "fromcurrent": True, "mode": "immediate",
                         "transition": {"duration": 300,
                                        "easing": "quadratic-in-out"},
                     }]),
                dict(label="⏸ Pause", method="animate",
                     args=[[None], {
                         "frame": {"duration": 0, "redraw": False},
                         "mode": "immediate",
                         "transition": {"duration": 0},
                     }]),
            ],
        )],
        sliders=[dict(
            # Open the timeline at the last frame (matches initial_traces).
            active=len(years_sorted) - 1,
            currentvalue={"prefix": "Year: "},
            x=0.12, xanchor="left", y=-0.05, yanchor="top",
            len=0.85, pad=dict(t=5, b=5),
            steps=[
                dict(method="animate",
                     args=[[str(yr)], {
                         "frame": {"duration": 300, "redraw": True},
                         "mode": "immediate",
                         "transition": {"duration": 300,
                                        "easing": "quadratic-in-out"},
                     }],
                     label=str(yr))
                for yr in years_sorted
            ],
        )],
    )
    return fig


def _rgba_from_hex(hex_color: str, alpha: float = 0.15) -> str:
    """Convert '#1f77b4' + alpha to an 'rgba(31,119,180,0.15)' string."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def build_ranking_bar(
    scored: pd.DataFrame,
    score_col: str,
    year: int,
    highlight: list[str],
    top_n: int | None = None,
) -> go.Figure:
    """Horizontal bar chart ranking all municipalities by score for one year."""
    sub = scored[scored["jaar"] == year].dropna(subset=[score_col]).copy()
    sub = sub.sort_values(score_col, ascending=True)
    if top_n is not None and len(sub) > top_n * 2:
        # Show only top & bottom N when too many municipalities to read.
        sub = pd.concat([sub.head(top_n), sub.tail(top_n)])

    sub = add_highlight_color_column(sub, highlight)

    fig = go.Figure(
        go.Bar(
            x=sub[score_col],
            y=sub["gemeente"],
            orientation="h",
            marker_color=sub["_color"],
            hovertemplate=(
                "<b>%{y}</b><br>" +
                SCORE_HUMAN[score_col] + ": %{x:.2f}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title=f"Municipalities ranked by {SCORE_HUMAN[score_col]} — {year}",
        xaxis_title=SCORE_HUMAN[score_col],
        yaxis_title="",
        height=max(400, 15 * len(sub)),
        margin=dict(l=120, r=20, t=60, b=40),
    )
    return fig


def build_evolution_lines(
    scored: pd.DataFrame,
    score_col: str,
    highlight: list[str],
) -> go.Figure:
    """
    Evolution chart with a clean two-layer context:

    - 5 thicker province-average lines (mean across municipalities of that
      province, per year) so regional patterns are visible at a glance.
    - 1 dashed black line for the Flemish average (mean across the five
      Flemish provinces, excluding Brussels-Capital).
    - On top: any user-highlighted municipalities in their full province
      colour, with markers and a clear legend label.

    Replaces the earlier 300+ grey-spaghetti context layer, which was
    unreadable at municipality density.
    """
    sub = scored.dropna(subset=[score_col])
    fig = go.Figure()

    # ---- Province averages (the new context layer) ----
    province_avg = (
        sub.groupby(["provincie", "jaar"])[score_col]
           .mean()
           .reset_index()
    )
    for prov, pdf in province_avg.groupby("provincie"):
        # Only the five Flemish provinces get a coloured province line —
        # Brussels is excluded from this layer to keep the chart focused
        # on Flanders. Selected Brussels municipalities still appear on
        # top if the user picks them.
        if prov not in FLEMISH_PROVINCES:
            continue
        pdf = pdf.sort_values("jaar")
        fig.add_trace(go.Scatter(
            x=pdf["jaar"], y=pdf[score_col],
            mode="lines",
            line=dict(color=PROVINCE_PALETTE.get(prov, "#888888"), width=2.5),
            name=f"{prov} (gemiddelde)",
            hovertemplate=(
                f"<b>{prov}</b> (provincie-gemiddelde)<br>"
                "Jaar: %{x}<br>" + SCORE_HUMAN[score_col] +
                ": %{y:.2f}<extra></extra>"
            ),
            opacity=0.85,
        ))

    # ---- Flemish overall average (dashed reference line) ----
    flemish = (
        sub[sub["provincie"].isin(FLEMISH_PROVINCES)]
           .groupby("jaar")[score_col]
           .mean()
           .reset_index()
           .sort_values("jaar")
    )
    fig.add_trace(go.Scatter(
        x=flemish["jaar"], y=flemish[score_col],
        mode="lines",
        line=dict(color="black", width=2.5, dash="dash"),
        name="Vlaanderen (gemiddelde)",
        hovertemplate=(
            "<b>Vlaanderen</b><br>Jaar: %{x}<br>" +
            SCORE_HUMAN[score_col] + ": %{y:.2f}<extra></extra>"
        ),
    ))

    # ---- Highlighted municipalities (drawn LAST so they sit on top) ----
    if highlight:
        focus = sub[sub["gemeente"].isin(highlight)]
        dash_for = municipality_dash_pattern(highlight)
        for gem, gdf in focus.groupby("gemeente"):
            gdf = gdf.sort_values("jaar")
            base_color = PROVINCE_PALETTE.get(
                gdf["provincie"].iloc[0], "#1f77b4"
            )
            fig.add_trace(go.Scatter(
                x=gdf["jaar"], y=gdf[score_col],
                mode="lines+markers",
                line=dict(color=base_color, width=4,
                          dash=dash_for.get(gem, "solid")),
                marker=dict(size=8, line=dict(color="white", width=1)),
                name=f"{gem} (selectie)",
                hovertemplate=(
                    f"<b>{gem}</b><br>Jaar: %{{x}}<br>"
                    f"{SCORE_HUMAN[score_col]}: %{{y:.2f}}<extra></extra>"
                ),
            ))

    fig.update_layout(
        title=(f"Evolution of {SCORE_HUMAN[score_col]} per province "
               f"(2014-2024)"),
        xaxis_title="Year",
        yaxis_title=SCORE_HUMAN[score_col],
        legend=dict(orientation="h", y=-0.2),
        hovermode="closest",
    )
    return fig


def build_animated_ranking(
    scored: pd.DataFrame,
    score_col: str,
    highlight: list[str],
    top_n: int | None = 20,
    scope_label: str | None = None,
) -> go.Figure:
    """
    Animated horizontal bar race over years.

    Shows top-N municipalities by score per year with a Play button.
    If `top_n` is None, all municipalities in the input are shown — useful
    once the caller has already narrowed the data (e.g. via a province
    filter) and wants the full filtered ranking to be visible.

    `scope_label` (e.g. 'Oost-Vlaanderen' or 'All Flanders') is woven into
    the chart title so screenshots stay self-explanatory.
    """
    sub = scored.dropna(subset=[score_col]).copy()

    frames_data = []
    for year, ydf in sub.groupby("jaar"):
        if top_n is not None:
            ydf = ydf.nlargest(top_n, score_col)
        ydf = ydf.sort_values(score_col)
        ydf = add_highlight_color_column(ydf, highlight)
        frames_data.append((year, ydf))

    # Initial frame = LAST year in the data (typically 2024) so the
    # ranking opens on the most recent snapshot instead of the oldest.
    first_year, first_df = frames_data[-1]

    # Fixed x-range across all frames — keeps bars from "jumping" left/right
    # as years change. Symmetric padding so labels at extremes stay visible.
    all_vals = sub[score_col]
    x_min, x_max = float(all_vals.min()), float(all_vals.max())
    x_pad = 0.05 * (x_max - x_min if x_max > x_min else 1.0)
    x_range = [x_min - x_pad, x_max + x_pad]

    # Adaptive height: every bar gets ~22 px so all municipality names fit.
    max_bars_per_frame = max(len(ydf) for _, ydf in frames_data)
    chart_height = max(400, 22 * max_bars_per_frame + 120)

    # ---- True bar-race pattern (full-screen safe) ----
    # Instead of swapping y-axis category order per frame (which Streamlit's
    # full-screen mode tends to drop), we encode the ranking directly in
    # the DATA: every frame uses NUMERIC y-positions 0..N-1 (lowest=bottom,
    # highest=top) and writes the municipality name onto its own bar as
    # text. The y-axis ticks are hidden — the bar's text label IS its
    # identifier. Moving a municipality up or down between years is then
    # just a data swap, which Plotly animates smoothly in any rendering
    # mode (inline, expanded, fullscreen).

    def _race_frame(ydf: pd.DataFrame) -> dict:
        """Sort ydf by score and return arrays ready for the bar race.

        Each bar's text label combines the municipality name and the
        rounded score so the value can be read off the bar itself —
        no x-axis lookup needed.
        """
        ranked = ydf.sort_values(score_col, ascending=True).reset_index(drop=True)
        labels = [f"{name}  ({val:+.2f})"
                  for name, val in zip(ranked["gemeente"], ranked[score_col])]
        return dict(
            x=ranked[score_col].values,
            y=list(range(len(ranked))),
            text=labels,
            colors=ranked["_color"].values,
        )

    f0 = _race_frame(first_df)

    fig = go.Figure(
        data=[go.Bar(
            x=f0["x"], y=f0["y"], orientation="h",
            marker_color=f0["colors"],
            text=f0["text"],
            textposition="outside",
            insidetextanchor="start",
            cliponaxis=False,
        )],
        frames=[
            go.Frame(
                data=[go.Bar(
                    x=(fr := _race_frame(ydf))["x"],
                    y=fr["y"],
                    orientation="h",
                    marker_color=fr["colors"],
                    text=fr["text"],
                    textposition="outside",
                    insidetextanchor="start",
                    cliponaxis=False,
                )],
                name=str(year),
            )
            for year, ydf in frames_data
        ],
    )
    count_prefix = (f"Top-{top_n} municipalities"
                    if top_n is not None
                    else f"All {max_bars_per_frame} municipalities")
    # Only append the scope suffix when a specific province is chosen;
    # the generic "All Flanders" label is redundant in the title.
    scope_suffix = (f" — {scope_label}"
                    if scope_label and scope_label != "All Flanders"
                    else "")
    fig.update_layout(
        title=(f"{count_prefix} by {SCORE_HUMAN[score_col]}"
               f"{scope_suffix} (animated 2014-2024)"),
        # X-axis title is dropped on purpose: it would otherwise overlap
        # the timeline slider that we placed flush against the plot area.
        # The chart title already names the score, so the axis stays
        # unambiguous.
        xaxis_title=None,
        yaxis_title="",
        height=chart_height,
        margin=dict(l=20, r=20, t=60, b=110),
        # X-axis is hidden — each bar carries its own score in the label,
        # so an axis would be redundant. We still keep the numeric range
        # so the bars stay proportional and don't squish around as years
        # change.
        xaxis=dict(
            range=x_range,
            fixedrange=False,
            showticklabels=False,
            showgrid=False,
            zeroline=False,
            showline=False,
        ),
        # Numeric y-axis with ticks hidden — the bar's text label is its
        # municipality name, which moves up/down with the ranking. Range
        # is fixed so the row positions stay constant across frames.
        yaxis=dict(
            range=[-1, max_bars_per_frame],
            showticklabels=False,
            showgrid=False,
            zeroline=False,
            fixedrange=True,
        ),
        # Play / Pause buttons sit on the same baseline as the year
        # timeline slider so the controls form one coherent strip at the
        # bottom of the chart.
        # IMPORTANT: every animate-args dict carries a matching
        # `transition` block. Without it, dragging the slider and then
        # pressing Play leaves Plotly in an inconsistent transition state
        # and the animation refuses to resume from the current frame.
        updatemenus=[dict(
            type="buttons",
            direction="left",
            showactive=False,
            x=0, xanchor="left",
            y=-0.05, yanchor="top",
            pad=dict(r=10, t=5),
            buttons=[
                dict(label="▶ Play", method="animate",
                     args=[None, {
                         "frame": {"duration": 800, "redraw": True},
                         "fromcurrent": True,
                         "transition": {"duration": 300,
                                        "easing": "quadratic-in-out"},
                         "mode": "immediate",
                     }]),
                dict(label="⏸ Pause", method="animate",
                     args=[[None], {
                         "frame": {"duration": 0, "redraw": False},
                         "mode": "immediate",
                         "transition": {"duration": 0},
                     }]),
            ],
        )],
        sliders=[dict(
            # Open the timeline at the last frame so the chart's initial
            # snapshot is the most recent year, matching `first_df` above.
            active=len(frames_data) - 1,
            currentvalue={"prefix": "Year: "},
            x=0.12, xanchor="left",
            y=0, yanchor="top",
            len=0.85,
            pad=dict(t=5, b=5),
            steps=[
                dict(method="animate",
                     args=[[str(year)], {
                         "frame": {"duration": 300, "redraw": True},
                         "mode": "immediate",
                         "transition": {"duration": 300,
                                        "easing": "quadratic-in-out"},
                     }],
                     label=str(year))
                for year, _ in frames_data
            ],
        )],
    )
    return fig


def build_core_scatter(
    scored: pd.DataFrame,
    highlight: list[str],
    animate: bool,
    year: int | None,
) -> go.Figure:
    """
    Core scatter: Dutch Language Pressure (X) vs Educational Strain (Y).

    Both modes draw the same overlays:
      - OLS regression line fitted on the current year's data
      - vertical dashed line at the current year's mean Dutch Language Pressure
      - horizontal dashed line at the current year's mean Educational Strain

    In animated mode all three overlays are recomputed PER FRAME — the
    regression slope, intercept and the two means glide along with the
    points as the year changes.
    """
    base = scored.dropna(subset=["language_pressure_score",
                                 "educational_outcome_score"]).copy()
    base = add_highlight_color_column(base, highlight)
    # Marker sizes are direct pixel diameters with go.Scatter (no implicit
    # rescaling like px.scatter's size_max), so we pick visible defaults.
    base["_size"] = np.where(base["gemeente"].isin(highlight), 20, 11)
    base["_text"] = np.where(
        base["gemeente"].isin(highlight), base["gemeente"], ""
    )

    # Global x/y ranges so the axes don't auto-rescale per frame (which
    # would make the OLS line jump around even when the data doesn't).
    x_min, x_max = base["language_pressure_score"].min(), base["language_pressure_score"].max()
    y_min, y_max = base["educational_outcome_score"].min(), base["educational_outcome_score"].max()
    x_pad = 0.05 * (x_max - x_min if x_max > x_min else 1)
    y_pad = 0.05 * (y_max - y_min if y_max > y_min else 1)
    x_range = [x_min - x_pad, x_max + x_pad]
    y_range = [y_min - y_pad, y_max + y_pad]

    def _overlays(year_df: pd.DataFrame):
        """Return (x_line, y_line, slope, intercept, x_mean, y_mean)."""
        x = year_df["language_pressure_score"].dropna().values
        y = year_df["educational_outcome_score"].dropna().values
        if len(x) < 3:
            return None
        slope, intercept = np.polyfit(x, y, 1)
        x_line = np.linspace(x_min, x_max, 50)
        y_line = intercept + slope * x_line
        return dict(
            x_line=x_line, y_line=y_line,
            slope=float(slope), intercept=float(intercept),
            x_mean=float(np.mean(x)), y_mean=float(np.mean(y)),
        )

    # Consistent province ordering across the dashboard.
    province_order = [p for p in FLEMISH_PROVINCES
                      if p in base["provincie"].unique()]
    if "Brussel (gewest)" in base["provincie"].unique():
        province_order.append("Brussel (gewest)")

    def _province_traces(df: pd.DataFrame) -> list[go.Scatter]:
        """
        Return one scatter trace per province in the data.

        Splitting by province gives Plotly a per-province legend entry
        with the matching colour swatch. Clicking a province in the
        legend hides/shows all its municipalities (single-click toggles,
        double-click isolates that province).

        To keep the legend swatch matching the evolution chart, marker
        colour here is ALWAYS the province colour. The highlight pattern
        is encoded via OPACITY instead (full opacity for selected munis,
        low for the rest) so the legend swatch stays clean per province.
        """
        traces = []
        has_highlight = bool(highlight)
        for prov in province_order:
            sub = df[df["provincie"] == prov]
            if sub.empty:
                continue
            province_colour = PROVINCE_PALETTE.get(prov, "#1f77b4")
            opacities = np.where(
                sub["gemeente"].isin(highlight), 1.0,
                0.35 if has_highlight else 0.85,
            )
            traces.append(go.Scatter(
                x=sub["language_pressure_score"],
                y=sub["educational_outcome_score"],
                mode="markers+text",
                marker=dict(
                    color=province_colour,
                    size=sub["_size"],
                    opacity=opacities,
                    line=dict(color="white", width=1),
                ),
                text=sub["_text"], textposition="top center",
                textfont=dict(size=11),
                customdata=np.stack(
                    [sub["gemeente"], sub["provincie"], sub["jaar"]], axis=-1),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Province: %{customdata[1]}<br>"
                    "Year: %{customdata[2]}<br>"
                    "Dutch Language Pressure: %{x:.2f}<br>"
                    "Educational Strain: %{y:.2f}<extra></extra>"
                ),
                name=prov,
                legendgroup=prov,
                showlegend=True,
                legendrank=province_order.index(prov),
            ))
        return traces

    def _make_ols_trace(ov):
        return go.Scatter(
            x=ov["x_line"], y=ov["y_line"],
            mode="lines",
            line=dict(color="black", width=2),
            hovertemplate=(
                f"OLS fit<br>y = {ov['intercept']:+.2f} "
                f"+ {ov['slope']:+.2f}·x<extra></extra>"
            ),
            showlegend=False, name="OLS",
        )

    def _make_vmean_trace(ov):
        return go.Scatter(
            x=[ov["x_mean"], ov["x_mean"]], y=y_range,
            mode="lines",
            line=dict(color="#666", width=1, dash="dot"),
            hovertemplate=f"mean X = {ov['x_mean']:+.2f}<extra></extra>",
            showlegend=False, name="mean_x",
        )

    def _make_hmean_trace(ov):
        return go.Scatter(
            x=x_range, y=[ov["y_mean"], ov["y_mean"]],
            mode="lines",
            line=dict(color="#666", width=1, dash="dot"),
            hovertemplate=f"mean Y = {ov['y_mean']:+.2f}<extra></extra>",
            showlegend=False, name="mean_y",
        )

    # ------------------------------------------------------------------
    # Static mode: one year, four traces (scatter + OLS + 2 mean lines).
    # ------------------------------------------------------------------
    if not animate:
        year_df = base[base["jaar"] == year]
        ov = _overlays(year_df)
        fig = go.Figure()
        for tr in _province_traces(year_df):
            fig.add_trace(tr)
        if ov is not None:
            fig.add_trace(_make_ols_trace(ov))
            fig.add_trace(_make_vmean_trace(ov))
            fig.add_trace(_make_hmean_trace(ov))
            fig.add_annotation(
                xref="paper", yref="paper", x=0.99, y=0.99,
                xanchor="right", yanchor="top",
                showarrow=False,
                text=(f"OLS: y = {ov['intercept']:+.2f} "
                      f"+ {ov['slope']:+.2f}·x<br>"
                      f"mean X = {ov['x_mean']:+.2f},  "
                      f"mean Y = {ov['y_mean']:+.2f}"),
                font=dict(size=11, color="#444"),
                bgcolor="rgba(255,255,255,0.8)", bordercolor="#aaa",
                borderwidth=1, borderpad=4,
            )
        fig.update_layout(
            title=f"Dutch Language Pressure vs Educational Strain — {year}",
            xaxis_title="Dutch Language Pressure Score (z)",
            yaxis_title="Educational Strain Score (z)",
            xaxis=dict(range=x_range), yaxis=dict(range=y_range),
            height=600,
            showlegend=True,
            legend=dict(
                title="Province (click to toggle)",
                orientation="v",
                yanchor="top", y=1.0,
                xanchor="left", x=1.02,
                itemsizing="constant",
            ),
        )
        return fig

    # ------------------------------------------------------------------
    # Animated mode: per-year frames. Each frame carries 4 traces
    # (scatter + OLS + vmean + hmean) so the regression line and mean
    # lines move along with the data as the year changes.
    # ------------------------------------------------------------------
    years_sorted = sorted(base["jaar"].unique().astype(int))
    years_data: dict[int, dict] = {}
    for yr in years_sorted:
        ydf = base[base["jaar"] == yr]
        years_data[yr] = dict(df=ydf, ov=_overlays(ydf))

    first_year = years_sorted[0]
    first = years_data[first_year]

    initial_traces = _province_traces(first["df"])
    if first["ov"]:
        initial_traces += [_make_ols_trace(first["ov"]),
                           _make_vmean_trace(first["ov"]),
                           _make_hmean_trace(first["ov"])]

    frames = []
    for yr in years_sorted:
        info = years_data[yr]
        frame_traces = _province_traces(info["df"])
        if info["ov"]:
            frame_traces += [_make_ols_trace(info["ov"]),
                             _make_vmean_trace(info["ov"]),
                             _make_hmean_trace(info["ov"])]
        # Annotation in the frame layout so the OLS equation text updates
        # together with the line.
        text = (f"OLS: y = {info['ov']['intercept']:+.2f} "
                f"+ {info['ov']['slope']:+.2f}·x<br>"
                f"mean X = {info['ov']['x_mean']:+.2f},  "
                f"mean Y = {info['ov']['y_mean']:+.2f}") if info["ov"] else ""
        frames.append(go.Frame(
            data=frame_traces, name=str(yr),
            layout=go.Layout(annotations=[dict(
                xref="paper", yref="paper", x=0.99, y=0.99,
                xanchor="right", yanchor="top", showarrow=False,
                text=text, font=dict(size=11, color="#444"),
                bgcolor="rgba(255,255,255,0.8)", bordercolor="#aaa",
                borderwidth=1, borderpad=4,
            )]),
        ))

    fig = go.Figure(data=initial_traces, frames=frames)
    if first["ov"]:
        fig.add_annotation(
            xref="paper", yref="paper", x=0.99, y=0.99,
            xanchor="right", yanchor="top", showarrow=False,
            text=(f"OLS: y = {first['ov']['intercept']:+.2f} "
                  f"+ {first['ov']['slope']:+.2f}·x<br>"
                  f"mean X = {first['ov']['x_mean']:+.2f},  "
                  f"mean Y = {first['ov']['y_mean']:+.2f}"),
            font=dict(size=11, color="#444"),
            bgcolor="rgba(255,255,255,0.8)", bordercolor="#aaa",
            borderwidth=1, borderpad=4,
        )

    fig.update_layout(
        title="Dutch Language Pressure vs Educational Strain — animated over years",
        xaxis_title="Dutch Language Pressure Score (z)",
        yaxis_title="Educational Strain Score (z)",
        xaxis=dict(range=x_range), yaxis=dict(range=y_range),
        height=600, margin=dict(l=60, r=30, t=60, b=110),
        showlegend=True,
        legend=dict(
            title="Province (click to toggle)",
            orientation="v",
            yanchor="top", y=1.0,
            xanchor="left", x=1.02,
            itemsizing="constant",
        ),
        updatemenus=[dict(
            type="buttons", direction="left", showactive=False,
            x=0, xanchor="left", y=-0.10, yanchor="top",
            pad=dict(r=10, t=5),
            buttons=[
                dict(label="▶ Play", method="animate",
                     args=[None, {
                         "frame": {"duration": 800, "redraw": True},
                         "fromcurrent": True, "mode": "immediate",
                         "transition": {"duration": 300,
                                        "easing": "quadratic-in-out"},
                     }]),
                dict(label="⏸ Pause", method="animate",
                     args=[[None], {
                         "frame": {"duration": 0, "redraw": False},
                         "mode": "immediate",
                         "transition": {"duration": 0},
                     }]),
            ],
        )],
        sliders=[dict(
            active=0, currentvalue={"prefix": "Year: "},
            x=0.12, xanchor="left", y=-0.05, yanchor="top",
            len=0.85, pad=dict(t=5, b=5),
            steps=[dict(method="animate",
                        args=[[str(yr)], {
                            "frame": {"duration": 300, "redraw": True},
                            "mode": "immediate",
                            "transition": {"duration": 300,
                                           "easing": "quadratic-in-out"},
                        }],
                        label=str(yr)) for yr in years_sorted],
        )],
    )
    return fig


def build_residual_bar(
    residuals: pd.DataFrame,
    year: int,
    highlight: list[str],
) -> go.Figure:
    """Residual bar chart: better/worse-than-expected outcome per gemeente."""
    sub = residuals[residuals["jaar"] == year].copy()
    sub = sub.sort_values("residual")
    sub = add_highlight_color_column(sub, highlight)

    fig = go.Figure(go.Bar(
        x=sub["residual"], y=sub["gemeente"], orientation="h",
        marker_color=sub["_color"],
        hovertemplate=("<b>%{y}</b><br>Residual: %{x:.2f}<br>"
                       "Negative = better than expected<br>"
                       "Positive = worse than expected<extra></extra>"),
    ))
    fig.update_layout(
        title=f"Better/worse-than-expected Educational Strain — {year}",
        xaxis_title="OLS residual (z-units)",
        yaxis_title="",
        height=max(400, 14 * len(sub)),
        margin=dict(l=120, r=20, t=60, b=40),
    )
    fig.add_vline(x=0, line=dict(color="black", width=1))
    return fig


def build_residual_evolution(
    residuals: pd.DataFrame,
    highlight: list[str],
) -> go.Figure:
    """
    Line chart of residual evolution over time per selected municipality.

    Earlier versions drew a grey spaghetti layer (one thin line per non-
    selected municipality) as context — but with 300+ municipalities that
    layer added clutter without informational value. We now show only the
    highlighted municipalities, the zero reference line, and an empty
    canvas if nothing is selected.

    The y-axis range is **fixed to the full Flemish residual range** so
    swapping selected municipalities never rescales the view: small
    fluctuations stay small visually, large deviations stay large. This
    avoids the optical illusion of every change looking dramatic just
    because Plotly auto-fit the axis to two cherry-picked lines.
    """
    fig = go.Figure()

    # Fixed axes based on the WHOLE Flemish residual sample, not the
    # selection — keeps the scale comparable across any choice. The range
    # is symmetric around zero so positive (worse-than-expected) and
    # negative (better-than-expected) deviations get equal visual weight.
    all_vals = residuals["residual"].dropna()
    if len(all_vals):
        max_abs = max(abs(float(all_vals.min())), abs(float(all_vals.max())))
        # 15 % headroom so the extreme points (e.g. Leuven at -2.2) sit
        # clearly inside the plot area, not right against the axis edge.
        max_abs *= 1.15
        y_range = [-max_abs, +max_abs]
    else:
        y_range = [-1, 1]
    years = sorted(residuals["jaar"].dropna().unique().astype(int).tolist())
    x_range = [years[0] - 0.3, years[-1] + 0.3] if years else None

    if not highlight:
        fig.add_annotation(
            xref="paper", yref="paper", x=0.5, y=0.5,
            xanchor="center", yanchor="middle", showarrow=False,
            text=("Select one or more municipalities in the sidebar to "
                  "see their residual evolution."),
            font=dict(size=14, color="#666"),
        )

    if highlight:
        focus = residuals[residuals["gemeente"].isin(highlight)]
        # Assign each highlighted municipality its OWN colour from a
        # palette that deliberately avoids green and red (those are used
        # for the better/worse-than-expected legend above the chart).
        # Sorted alphabetically so the colour-to-name mapping is stable
        # across re-runs.
        ordered_munis = sorted(focus["gemeente"].unique())
        colour_for = {gem: HIGHLIGHT_PALETTE[i % len(HIGHLIGHT_PALETTE)]
                      for i, gem in enumerate(ordered_munis)}
        for gem in ordered_munis:
            gdf = focus[focus["gemeente"] == gem].sort_values("jaar")
            fig.add_trace(go.Scatter(
                x=gdf["jaar"], y=gdf["residual"],
                mode="lines+markers",
                line=dict(color=colour_for[gem], width=3),
                marker=dict(size=8, line=dict(color="white", width=1)),
                name=gem,
                hovertemplate=(f"<b>{gem}</b><br>Year: %{{x}}<br>"
                               "Residual: %{y:.2f}<extra></extra>"),
            ))

    fig.add_hline(y=0, line=dict(color="black", width=1, dash="dot"))
    fig.update_layout(
        title="Residual evolution: persistent over- or under-performance?",
        xaxis_title="Year",
        yaxis_title="OLS residual (z-units)",
        legend=dict(orientation="h", y=-0.2),
        # autorange=False is critical: without it Plotly's defaults can
        # re-fit the axis to the visible traces and our fixed scale gets
        # ignored when only one or two municipalities are selected.
        xaxis=dict(range=x_range, dtick=1, autorange=False),
        yaxis=dict(range=y_range, autorange=False),
    )
    return fig


def build_radar(
    enriched: pd.DataFrame,
    highlight: list[str],
    year: int,
) -> go.Figure:
    """
    Radar chart comparing 1-5 municipalities across the six component
    indicators for a single year. Values are min-max scaled within the year
    so axes are comparable.

    Municipality colours follow the alphabetical-to-HIGHLIGHT_PALETTE
    mapping shared with Tab 4 and the rest of Tab 5, so a given
    municipality keeps the same colour across all per-municipality views.
    """
    components = [
        "pct_nl_primary", "pct_nl_secondary", "newcomers_per_1000_adults",
        "pct_delay_secondary", "pct_early_school_leavers", "enrollment_rate_avg",
    ]
    year_df = enriched[(enriched["jaar"] == year) &
                       (enriched["indicator"].isin(components))]

    if year_df.empty:
        return go.Figure().update_layout(
            title=f"No data available for radar chart in {year}.")

    wide = year_df.pivot_table(
        index="gemeente", columns="indicator", values="waarde", aggfunc="first"
    )

    # Min-max scale per component across all municipalities of this year so
    # the radar axes are directly comparable.
    scaled = (wide - wide.min()) / (wide.max() - wide.min()).replace(0, np.nan)

    # Same alphabetical assignment as the residual chart in Tab 4 and the
    # raw-indicator lines in this tab.
    colour_map = {
        gem: HIGHLIGHT_PALETTE[i % len(HIGHLIGHT_PALETTE)]
        for i, gem in enumerate(sorted(highlight))
    }

    fig = go.Figure()
    for gem in sorted(highlight):
        if gem not in scaled.index:
            continue
        row = scaled.loc[gem].reindex(components)
        colour = colour_map[gem]
        fig.add_trace(go.Scatterpolar(
            r=row.values,
            theta=[INDICATOR_DISPLAY[c] for c in components],
            fill="toself",
            name=gem,
            line=dict(color=colour),
            fillcolor=colour,
            opacity=0.4,
        ))

    fig.update_layout(
        title=f"Indicator profile (min-max within {year})",
        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
        showlegend=True,
        height=500,
    )
    return fig


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar(
    scored: pd.DataFrame,
    long_df: pd.DataFrame,
) -> dict:
    """
    Render the global sidebar. Stores selections in st.session_state so the
    highlight pattern persists across tabs.

    Parameters
    ----------
    scored : pd.DataFrame
        Scored data already filtered to "score-complete" years.
    long_df : pd.DataFrame
        Tidy long-format raw data (full year range — for diagnostics).

    Returns
    -------
    dict
        Resolved selections: provinces, municipalities, year.
    """
    st.sidebar.title("🎛 Controls")
    st.sidebar.caption("Selections persist as you switch tabs.")

    # Read the Brussels-toggle state EARLY so the municipality eligibility
    # list below can react to it. The actual toggle widget is rendered
    # further down (after the multiselect) — Streamlit reads/writes the
    # widget value through `st.session_state["include_brussels"]`, which
    # is set whenever the widget was rendered in the previous run.
    include_brussels_state = st.session_state.get("include_brussels", False)

    # --- Municipalities ---
    # The highlight pool follows the Brussels toggle state.
    if include_brussels_state:
        eligible = sorted(scored["gemeente"].dropna().unique().tolist())
    else:
        eligible = sorted(
            scored.loc[scored["provincie"] != "Brussel (gewest)",
                       "gemeente"].dropna().unique().tolist()
        )
    st.session_state.setdefault("highlight_municipalities", [])
    current_selection = [m for m in st.session_state["highlight_municipalities"]
                         if m in eligible]
    # Custom heading above the multiselect — larger and bold than the
    # default widget label. The widget's own label is hidden via
    # label_visibility so we don't get two stacked titles.
    st.sidebar.markdown("### **Highlight municipalities**")
    highlight = st.sidebar.multiselect(
        "Highlight municipalities",
        options=eligible,
        default=current_selection,
        help=("Selected municipalities appear in their province colour; "
              "everything else is rendered with low opacity as context. "
              "Leave empty to see all in colour."),
        label_visibility="collapsed",
    )
    st.session_state["highlight_municipalities"] = highlight

    # --- Brussels-Capital toggle ---
    # When on (default), the dashboard shows all 304 municipalities
    # including the 19 Brussels-Capital communes. When off, only the
    # five Flemish provinces are shown — useful when the user wants to
    # see how Flanders looks without Brussels' systematic outlier pull.
    st.sidebar.markdown("**Geographic scope**")
    include_brussels = st.sidebar.toggle(
        "Include Brussels-Capital (19 communes)",
        value=include_brussels_state,
        key="include_brussels",
        help=("Toggle off to restrict every chart, regression and OLS "
              "residual to the five Flemish provinces."),
    )
    if include_brussels:
        st.sidebar.caption(
            "⚠️ **Heavy effect on the regression and ranking.** "
            "Brussels-Capital communes have very low Dutch-at-home rates "
            "(French-/multilingual-speaking majority) and structurally high "
            "newcomers per capita. They sit far to the right of the Language "
            "Pressure axis and tend to pull the OLS regression slope and "
            "the score distribution upward. Toggling them off gives the "
            "'Flanders-only' picture."
        )
    else:
        st.sidebar.info(
            "🇧🇪 Brussels-Capital communes are **hidden**. "
            "Regression, residuals, ranking and distributions are computed "
            "on the five Flemish provinces only."
        )

    # --- Colour palette selector ---
    # Lets the user switch to a colour-blind-safe palette (Wong 2011)
    # for every chart that uses province colours. The default palette
    # contains red (West-Vlaanderen) and green (Limburg) which are
    # hard to distinguish for the ~8 % of (male) viewers with red-green
    # deficiency.
    st.sidebar.markdown("**Colour palette**")
    palette_choice = st.sidebar.selectbox(
        "Province colour palette",
        options=list(PROVINCE_PALETTES.keys()),
        index=list(PROVINCE_PALETTES.keys()).index(
            st.session_state.get("palette_choice", "Default")
        ),
        key="palette_choice",
        help=("'Colour-blind safe' uses Wong (2011) palette — six hues "
              "distinguishable under protanopia, deuteranopia and "
              "tritanopia."),
    )

    # Year for the cross-sectional views (histogram, ranking, static
    # scatter, radar) is fixed to the most recent score-complete year —
    # currently 2024. When the upstream source publishes a complete 2025
    # the year picker automatically advances; no manual edit needed.
    years = available_years(scored)
    selected_year = years[-1]

    st.sidebar.markdown("---")
    st.sidebar.caption(SCORE_CAVEAT)

    return dict(
        municipalities=highlight,
        year=selected_year,
        include_brussels=include_brussels,
        palette_choice=palette_choice,
    )


# ---------------------------------------------------------------------------
# Tab renderers
# ---------------------------------------------------------------------------

def render_intro_tab():
    """
    Tab 0 — onboarding for first-time users.

    Explains the purpose of the barometer, the two composite scores, how
    the controls work, the meaning of each downstream tab and the main
    interpretation caveats. Aimed at policy-makers without a statistics
    background.
    """
    st.header("Welcome to the Flanders Language & Education Barometer")
    st.markdown(
        "This dashboard is a **policy barometer**: a longitudinal "
        "monitoring tool for the relationship between **language context** "
        "and **educational outcomes** across Flemish municipalities, "
        "2014-2024."
    )

    # ---- Acronyms (kept up front so policy-language readers can refer
    # back to them while reading the rest of the intro and the tabs). ----
    with st.expander("📖 Acronyms used in this dashboard"):
        st.markdown(
            "Both **NT2** and **OKAN** belong to the Flemish education and "
            "language-integration landscape; they appear in the "
            "auto-analysis policy advice (Tab 5).\n\n"
            "- **NT2 — *Nederlands als Tweede Taal*** ('Dutch as a "
            "Second Language'). The umbrella term for the course or "
            "trajectory in which youngsters and adults learn Dutch when "
            "their mother tongue is something else. The focus is on "
            "language acquisition and integration, and the term is used "
            "for both school programmes and adult-education courses.\n\n"
            "- **OKAN — *Onthaalklas voor Anderstalige Nieuwkomers*** "
            "('Reception class for non-Dutch-speaking newcomers'). A "
            "specific, intensive reception programme in secondary "
            "education. Children and adolescents between 12 and 18 who "
            "arrived in Belgium recently and do not speak Dutch attend "
            "an OKAN class full-time for one year — Dutch language "
            "lessons plus social support — before transitioning to "
            "mainstream secondary education.\n\n"
            "- **Huizen van het Kind** — local cross-sector hubs "
            "supporting families with young children, often a touchpoint "
            "for early-childhood Dutch-language exposure."
        )

    st.markdown("---")

    # ---- What the dashboard answers ----
    st.subheader("What questions does it answer?")
    st.markdown(
        "- _Which municipalities face the highest pressure on Dutch language "
        "use in schools, and where is that pressure rising?_\n"
        "- _Where are educational outcomes most strained — and is the "
        "strain getting better or worse?_\n"
        "- _Are these two phenomena linked, and which municipalities "
        "deviate from that link (positively or negatively)?_\n"
        "- _For one or a few municipalities of interest, what is the "
        "indicator profile and how does it evolve over time?_"
    )

    # ---- The two scores ----
    st.subheader("The two composite scores")
    col_lp, col_es = st.columns(2)
    with col_lp:
        st.markdown(
            "### 🗣️ Dutch Language Pressure Score\n"
            "How much pressure does the local language context put on "
            "Dutch-medium schooling?\n\n"
            "**Components** (z-scored within each year, then averaged):\n"
            "- % primary pupils not speaking Dutch at home\n"
            "- % secondary pupils not speaking Dutch at home\n"
            "- newcomers per 1 000 adults (18+) — a **leading proxy** "
            "for future language pressure (today's adult newcomers are "
            "tomorrow's pupil parents)"
        )
    with col_es:
        st.markdown(
            "### 🎓 Educational Strain Score\n"
            "How strained are educational outcomes in this municipality?\n\n"
            "**Components** (z-scored within each year, then averaged):\n"
            "- % secondary pupils with 2+ years of delay\n"
            "- % early school leavers\n"
            "- average enrollment rate (3-17), capped at 100 and reversed "
            "so that *lower* enrollment contributes to *higher* strain"
        )

    with st.expander("📐 What does 'z-scored within each year' mean?"):
        st.markdown(
            "Each component indicator is **standardised** within each year, "
            "across all Flemish municipalities, to have mean 0 and "
            "standard deviation 1. So a score of **+1** means *roughly one "
            "standard deviation above the Flemish average in that year* — "
            "high pressure / high strain. A score of **-1** means one "
            "standard deviation below — low pressure / low strain.\n\n"
            "**Why it matters:** scores are directly comparable **between** "
            "municipalities **in the same year**, but they are *not* "
            "directly comparable across years (a +1 in 2014 reflects the "
            "2014 distribution, not the 2024 one). Trends over time still "
            "show whether a municipality is moving up or down relative to "
            "the rest of Flanders."
        )

    # ---- Controls ----
    st.subheader("Controls (sidebar, left)")
    st.markdown(
        "- **Include Brussels-Capital toggle.** Brussels-Capital communes "
        "have very low Dutch-at-home rates by definition (French-speaking "
        "majority) and structurally high newcomer rates. They sit far to "
        "the right of the Dutch Language Pressure axis and **pull the "
        "OLS regression line upward**. Toggle them off to see the "
        "'Flanders-only' picture.\n"
        "- **Highlight municipalities.** Pick one or more — they appear in "
        "their own colour while the rest fades to context. The selection "
        "**persists across tabs** so you can follow a municipality through "
        "every view."
    )

    # ---- Tabs ----
    st.subheader("What each tab contains")
    st.markdown(
        "| Tab | What you see |\n"
        "|---|---|\n"
        "| **1. Dutch Language Pressure** | Distribution per province (KDE), "
        "evolution over time (5 province averages + Flanders reference), "
        "animated municipal ranking per chosen province. |\n"
        "| **2. Educational Strain** | Same structure as tab 1 but for the "
        "outcome strain score. |\n"
        "| **3. Scatter** | Both scores on one chart, one point per "
        "municipality. OLS regression + mean reference lines update **per "
        "year** in animated mode. |\n"
        "| **4. Trend & Deviation** | Residuals from the OLS regression "
        "(better / worse than expected, given language pressure) plotted "
        "over time per selected municipality. Baseline selectable: all "
        "Flanders or one province. |\n"
        "| **5. Municipal detail** | Per selected municipality: an "
        "auto-generated narrative summary, six raw indicators over time "
        "(with the Flemish average), a radar profile, and a downloadable "
        "CSV table. |"
    )

    # ---- Caveats ----
    st.subheader("Interpretation caveats")
    st.warning(
        "**Within-year normalisation.** Z-scores describe relative "
        "position *within a year*. A municipality scoring +1.5 in 2014 "
        "and +1.5 in 2024 has stayed at the same relative position — "
        "absolute values in the underlying indicators may have shifted.",
    )
    st.warning(
        "**2025 not yet score-complete.** The 'newcomers' and 'early "
        "school leavers' indicators are still empty for 2025 in the "
        "source data. Score-based tabs therefore stop at 2024; raw "
        "indicator views in tab 5 still show 2025 where data exists."
    )
    st.warning(
        "**Indicator scope is 'not Dutch at home', not 'foreign'.** "
        "The Dutch language indicator counts pupils whose home language "
        "is not Dutch — it does NOT track nationality. Dutch nationals "
        "(e.g. in border municipalities) speak Dutch at home and are "
        "correctly classified as Dutch-speakers. Residual patterns in "
        "border areas therefore reflect genuine school performance, not "
        "a measurement artefact."
    )
    st.warning(
        "**Correlation, not causation.** Every scatter, regression line "
        "and residual in this dashboard describes a *statistical "
        "association* between language pressure and educational "
        "outcomes. It does **not prove** that one *causes* the other. "
        "Many confounders are in play — socio-economic status, school "
        "capacity and staffing, family stability, pupil mobility, "
        "selection effects between schools, cohort composition. It is "
        "plausible that not speaking Dutch at home has a real causal "
        "effect on outcomes in Dutch-medium education, but quantifying "
        "that effect requires causal-inference methods (instrumental "
        "variables, longitudinal cohort designs, matched comparisons) "
        "that this monitoring tool does not perform."
    )

    # ---- Data source ----
    st.subheader("Data source")
    st.markdown(
        "Indicators are sourced from **provincies.incijfers.be** "
        "(Statistiek Vlaanderen / Statbel), reshaped from the wide-format "
        "export into a tidy long DataFrame, and composited locally. "
        "Score calculations and province assignments are deterministic "
        "and reproducible — see `compute_scores.py` and `config.py`."
    )



def render_score_tab(
    title: str,
    score_col: str,
    scored: pd.DataFrame,
    selections: dict,
):
    """Shared renderer for Tab 1 (Dutch Language Pressure) and Tab 2 (Outcome)."""
    st.header(title)
    # Score description (components, formula, caveats) is collapsed by
    # default — most users want the charts first; the formula stays one
    # click away for those who care about the maths.
    with st.expander(f"📐 How is the {title} Score built? (click to expand)",
                     expanded=False):
        st.markdown(SCORE_DESCRIPTIONS[score_col])

    # No province pre-filter — every Flemish municipality is in every
    # chart by default. Tab-local pills (e.g. the ranking) can still
    # narrow specific views.
    scoped = scored

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            build_histogram(scoped, score_col,
                            selections["year"], selections["municipalities"]),
            width="stretch",
        )
    with col2:
        st.plotly_chart(
            build_evolution_lines(scoped, score_col, selections["municipalities"]),
            width="stretch",
        )

    # ---- Per-ranking single-province pill (independent of the sidebar) ----
    # Always one specific province in view — keeps the bar race readable
    # and the title self-explanatory. The province name appears in the
    # chart title for clarity on exports / screenshots.
    province_pill_options = [
        p for p in FLEMISH_PROVINCES + ["Brussel (gewest)"]
        if p in scoped["provincie"].unique()
    ]
    st.markdown("#### Ranking")
    chosen_province = st.pills(
        "Choose ONE province for the ranking:",
        options=province_pill_options,
        default=province_pill_options[0],
        selection_mode="single",
        key=f"ranking_pill_{score_col}",
        help="Narrows ONLY the ranking chart below.",
    ) or province_pill_options[0]

    ranking_scope = scoped[scoped["provincie"] == chosen_province]

    st.plotly_chart(
        build_animated_ranking(ranking_scope, score_col,
                               selections["municipalities"],
                               top_n=None,
                               scope_label=chosen_province),
        width="stretch",
    )
    st.caption(
        "ℹ️ Note: opening this chart in **fullscreen** (the 🗖 icon top-right) "
        "freezes it on the currently-selected year — the Play button and "
        "timeline only work in the normal view. For a bigger picture, use "
        "your browser's zoom (Ctrl + scroll) or full-screen the whole tab "
        "with F11."
    )

    st.caption(SCORE_CAVEAT)


def render_scatter_tab(scored: pd.DataFrame, selections: dict):
    """Tab 3 — the core scatter, with animation toggle."""
    st.header("Dutch Language Pressure × Educational Strain")
    st.markdown(
        "Each point is a municipality in the chosen year. "
        "X measures relative language-context pressure; Y measures "
        "relative outcome-pressure (higher = worse outcomes). "
        "Use the animation to watch positions shift over time."
    )

    scoped = scored  # all provinces always included

    animate = st.toggle(
        "▶ Animate over years",
        value=True,
    )

    st.plotly_chart(
        build_core_scatter(
            scoped, selections["municipalities"], animate,
            year=selections["year"],
        ),
        width="stretch",
    )

    st.caption(
        "⚠️ The OLS line shows the **statistical association** between "
        "the two scores across Flemish municipalities in a given year. "
        "It is **not a causal model**: it does not establish that "
        "language pressure *causes* the outcome strain, only that they "
        "tend to move together at the municipal level. Many confounders "
        "(socio-economic status, school capacity, mobility) sit outside "
        "this view."
    )
    st.caption(SCORE_CAVEAT)


def render_trend_tab(scored: pd.DataFrame, selections: dict):
    """Tab 4 — OLS residual evolution over time (single view)."""
    st.header("Trend & Deviation Analysis")
    st.markdown(
        "**OLS residual** answers: _given a municipality's Dutch language "
        "pressure, is its educational outcome better or worse than the "
        "regression predicts?_ The line chart shows how that deviation "
        "evolves over time per municipality."
    )

    # Prominent two-column legend so the sign convention can't be missed.
    leg_left, leg_right = st.columns(2)
    leg_left.success(
        "🟢 **Negative residual** — municipality performs **BETTER** "
        "than the regression line predicts (lower-than-expected strain "
        "given its language pressure)."
    )
    leg_right.error(
        "🔴 **Positive residual** — municipality performs **WORSE** "
        "than the regression line predicts (higher-than-expected strain "
        "given its language pressure)."
    )
    st.caption(
        "⚠️ The OLS regression is a **descriptive association**, not a "
        "causal model. Residuals flag municipalities whose outcomes "
        "deviate from the Flemish average pattern; they do **not** "
        "quantify the causal effect of language pressure on outcomes. "
        "Many confounders (socio-economic status, school capacity, "
        "pupil mobility, …) are not in this model. Dutch proficiency "
        "likely has a real effect on outcomes in Dutch-medium "
        "education, but isolating that effect needs causal-inference "
        "methods this dashboard does not perform."
    )

    # ---- Trend baseline selector ----
    # The OLS regression can be fit on:
    #   - all available municipalities (Flanders-wide baseline, default), or
    #   - a single province's municipalities (regional baseline).
    # A regional baseline answers "compared to the pattern in MY province,
    # is this municipality better or worse?" which is often more relevant
    # for policy-makers working at provincial level.
    available_provinces = sorted([
        p for p in FLEMISH_PROVINCES + ["Brussel (gewest)"]
        if p in scored["provincie"].unique()
    ])
    baseline_options = ["Flanders (all provinces)"] + available_provinces
    baseline = st.radio(
        "Regression baseline",
        options=baseline_options,
        index=0,
        horizontal=True,
        help=("Choose which set of municipalities the OLS regression is "
              "fitted on. The residual of each municipality is computed "
              "against that baseline."),
        key="trend_baseline",
    )

    if baseline == "Flanders (all provinces)":
        scoped = scored
        baseline_label = "Flanders (all provinces)"
    else:
        scoped = scored[scored["provincie"] == baseline]
        baseline_label = baseline

    residuals = ols_residuals_per_year(scoped)

    fig = build_residual_evolution(residuals, selections["municipalities"])
    fig.update_layout(
        title=(f"Residual evolution vs. {baseline_label} baseline: "
               "persistent over- or under-performance?")
    )
    st.plotly_chart(fig, width="stretch")

    # Friendly warning if the user highlighted a municipality that is NOT
    # part of the chosen baseline (e.g. baseline = Antwerpen, highlight =
    # Gent). Without this they'd see an empty chart and wonder why.
    if selections["municipalities"]:
        missing = [m for m in selections["municipalities"]
                   if m not in residuals["gemeente"].unique()]
        if missing:
            st.info(
                f"ℹ️ Not shown: {', '.join(missing)} — outside the chosen "
                f"baseline ({baseline_label}). Pick a different baseline "
                "or another municipality."
            )

    st.caption(SCORE_CAVEAT)


def render_detail_tab(
    scored: pd.DataFrame,
    enriched: pd.DataFrame,
    selections: dict,
):
    """Tab 5 — per-indicator evolution, radar comparison, downloadable table."""
    st.header("Municipal detail & comparison")

    selected = selections["municipalities"]
    if not selected:
        st.info(
            "👉 Select **1-5 municipalities** in the sidebar to populate "
            "this tab."
        )
        return
    if len(selected) > 5:
        st.warning(
            f"You have {len(selected)} municipalities selected. The radar "
            "becomes hard to read above 5; consider narrowing the focus."
        )

    # ---- Auto-analysis (rule-based, no AI) ----
    st.subheader("Auto-analysis")
    st.caption(
        "📂 **Click the headers below to expand** a per-municipality summary "
        "generated from the data via fixed rules. Same numbers as the "
        "charts below; conservative phrasing; fully reproducible. "
        "Acronyms used in the policy advice (**NT2**, **OKAN**, "
        "*Huizen van het Kind*) are defined in **Tab 0 → Acronyms**."
    )
    residuals_full = ols_residuals_per_year(scored)
    for gem in selected:
        with st.expander(f"📋 Auto-analysis — **{gem}** (click to expand)",
                         expanded=False):
            result = analyse_municipality(
                scored, residuals_full,
                gemeente=gem, year=selections["year"],
            )
            st.markdown(result["markdown"])
            if result["student_city_caveat"]:
                # Small yellow callout, visually separated from the main
                # policy paragraph above.
                st.warning(result["student_city_caveat"])

    # ---- Raw indicators evolution ----
    st.subheader("Raw indicators over time")
    st.caption(
        "Coloured lines = selected municipalities. The **dashed black line** "
        "is the **unweighted mean across the five Flemish provinces' "
        "municipalities** (every municipality counts equally, Brussels-"
        "Capital excluded). It is therefore NOT the same as a population-"
        "weighted 'Flanders as a whole' figure: a small municipality "
        "weighs as much as Antwerp here, so this line lies closer to the "
        "*typical municipality* than to the Flemish *aggregate*. Reading "
        "tip: it answers \"how does my municipality compare to a typical "
        "Flemish municipality?\", not \"how does it compare to Flanders "
        "as a single block of residents?\"."
    )
    indicator_keys = [
        "pct_nl_primary", "pct_nl_secondary", "newcomers_per_1000_adults",
        "pct_delay_secondary", "pct_early_school_leavers", "enrollment_rate_avg",
    ]
    sub = enriched[enriched["gemeente"].isin(selected) &
                   enriched["indicator"].isin(indicator_keys)]

    # Flemish average per (indicator, year): mean across the five Flemish
    # provinces only — Brussels-Capital is excluded so the reference line
    # describes the "Vlaanderen" context the user really compares against.
    flemish_only = enriched[
        enriched["provincie"].isin(FLEMISH_PROVINCES)
        & enriched["indicator"].isin(indicator_keys)
    ]
    flanders_avg = (
        flemish_only.dropna(subset=["waarde"])
                    .groupby(["indicator", "jaar"])["waarde"]
                    .mean()
                    .reset_index()
    )

    # Per-municipality colour mapping — same alphabetical-to-palette
    # assignment as Tab 4's residual chart, so a given municipality
    # gets the SAME colour across Tab 4 and Tab 5. HIGHLIGHT_PALETTE is
    # already colour-blind safe (no red, no green), so this also avoids
    # the better/worse-callout clash in Tab 4.
    muni_colour_map = {
        gem: HIGHLIGHT_PALETTE[i % len(HIGHLIGHT_PALETTE)]
        for i, gem in enumerate(sorted(selected))
    }

    cols = st.columns(2)
    for i, ind in enumerate(indicator_keys):
        # Apply the per-indicator display scaling (×100 for fractions, ‰
        # / % suffix). Calculations elsewhere use the raw value; this is
        # purely a presentation step.
        mult, unit = INDICATOR_DISPLAY_SCALE.get(ind, (1.0, ""))
        ind_data = sub[sub["indicator"] == ind].copy()
        ind_data["_display"] = ind_data["waarde"] * mult
        avg_ind = flanders_avg[flanders_avg["indicator"] == ind].copy()
        avg_ind["_display"] = avg_ind["waarde"] * mult

        y_axis_label = f"Value ({unit})" if unit else "Value"
        fig = px.line(
            ind_data.sort_values(["gemeente", "jaar"]),
            x="jaar", y="_display", color="gemeente",
            markers=True,
            title=INDICATOR_DISPLAY[ind],
            labels={"jaar": "Year", "_display": y_axis_label},
            color_discrete_map=muni_colour_map,
        )
        # Uniform hover label across the per-municipality traces.
        fig.update_traces(
            hovertemplate=("<b>%{fullData.name}</b><br>Year: %{x}<br>"
                           f"Value: %{{y:.2f}}{unit}<extra></extra>"),
        )
        if not avg_ind.empty:
            avg_sorted = avg_ind.sort_values("jaar")
            fig.add_trace(go.Scatter(
                x=avg_sorted["jaar"], y=avg_sorted["_display"],
                mode="lines",
                line=dict(color="black", width=2, dash="dash"),
                name="Avg of Flemish municipalities",
                hovertemplate=(
                    "<b>Average of Flemish municipalities</b><br>"
                    "<i>(unweighted, every gemeente counts once)</i><br>"
                    f"Year: %{{x}}<br>Value: %{{y:.2f}}{unit}"
                    "<extra></extra>"
                ),
            ))
        fig.update_layout(
            legend=dict(orientation="h", y=-0.25),
            # Y-axis always starts at zero so small differences don't get
            # visually exaggerated by Plotly's auto-zoom on the data range.
            yaxis=dict(rangemode="tozero", ticksuffix=unit),
        )
        with cols[i % 2]:
            st.plotly_chart(fig, width="stretch")
            st.caption(INDICATOR_TOOLTIP[ind])

    # ---- Radar ----
    st.subheader(f"Indicator profile snapshot — {selections['year']}")
    st.plotly_chart(
        build_radar(enriched, selected, selections["year"]),
        width="stretch",
    )
    st.caption(
        "Values are min-max scaled within the chosen year so that all "
        "indicators share the [0, 1] axis range. 1 = the highest observed "
        "value among Flemish municipalities that year."
    )

    # ---- Downloadable table ----
    st.subheader("Underlying data (downloadable)")
    st.caption(
        "Percentage indicators are shown on a 0-100 scale (fractions in "
        "the source Excel have been multiplied by 100 for readability)."
    )
    table = scored[scored["gemeente"].isin(selected)].sort_values(
        ["gemeente", "jaar"]
    )
    raw_cols = [
        "pct_nl_primary", "pct_nl_secondary", "newcomers_per_1000_adults",
        "pct_delay_secondary", "pct_early_school_leavers", "enrollment_rate_avg",
    ]
    display = table[[
        "gemeente", "provincie", "jaar",
        "language_pressure_score", "educational_outcome_score",
        *raw_cols,
    ]].copy()
    # Apply per-indicator display scaling (×100 for fractions, otherwise
    # no-op) so the table matches the charts.
    rename_map = {}
    for col in raw_cols:
        mult, unit = INDICATOR_DISPLAY_SCALE.get(col, (1.0, ""))
        display[col] = display[col] * mult
        if unit:
            rename_map[col] = f"{col} ({unit})"
    display = display.rename(columns=rename_map)
    st.dataframe(display, width="stretch", hide_index=True)

    csv_buffer = io.StringIO()
    display.to_csv(csv_buffer, index=False)
    st.download_button(
        "⬇ Download CSV",
        data=csv_buffer.getvalue(),
        file_name=f"barometer_export_{'-'.join(selected)[:80]}.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    """Wire everything together."""
    st.set_page_config(
        page_title="Flanders Language & Education Barometer",
        page_icon="🏫",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("Flanders Language & Education Policy Barometer")
    st.markdown(
        "A longitudinal monitoring tool for the relationship between "
        "**language context** and **educational outcomes** in Flemish "
        "municipalities, 2014-2024."
    )

    long_df = cached_long_format()
    h = len(long_df)  # stable in-session, forces cache key
    scored_full = cached_scores(h, long_df)
    enriched = cached_enriched(h, long_df)

    # Drop years for which one of the score components is entirely missing
    # in the source data (e.g. 2025: no 'newcomers' or 'early leavers' yet).
    # Score-based tabs (1-4) use this filtered view; the raw-indicator tab 5
    # still uses the full enriched data so individual indicators that DO
    # exist in the incomplete year remain visible.
    scored, _excluded_years = filter_scored_to_complete_years(
        scored_full, long_df
    )

    selections = render_sidebar(scored, long_df)

    # Apply the user's palette choice. We mutate BOTH palettes in place
    # so every chart builder (province palette for Tabs 1-3, highlight
    # palette for Tabs 4-5) sees the new colours on this run — no need
    # to plumb the palette through every function signature.
    palette_choice = selections["palette_choice"]
    PROVINCE_PALETTE.clear()
    PROVINCE_PALETTE.update(PROVINCE_PALETTES[palette_choice])
    HIGHLIGHT_PALETTE.clear()
    HIGHLIGHT_PALETTE.extend(HIGHLIGHT_PALETTES[palette_choice])

    # Apply the Brussels-Capital toggle: when off, every score-based tab
    # works on the Flemish subset only. Z-scores themselves were computed
    # on ALL municipalities (including Brussels) so an individual muni's
    # value doesn't change — what changes is which points are visible AND
    # which points the regression line in Tab 3 / OLS residuals in Tab 4
    # are fitted on.
    if not selections["include_brussels"]:
        scored_view = scored[scored["provincie"] != "Brussel (gewest)"]
    else:
        scored_view = scored

    tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "0. Intro",
        "1. Dutch Language Pressure",
        "2. Educational Strain",
        "3. Scatter",
        "4. Trend & Deviation",
        "5. Municipal Detail",
    ])

    with tab0:
        render_intro_tab()
    with tab1:
        render_score_tab(
            "Dutch Language Pressure",
            "language_pressure_score",
            scored_view, selections,
        )
    with tab2:
        render_score_tab(
            "Educational Strain",
            "educational_outcome_score",
            scored_view, selections,
        )
    with tab3:
        render_scatter_tab(scored_view, selections)
    with tab4:
        render_trend_tab(scored_view, selections)
    with tab5:
        # Tab 5: raw indicators are useful even in score-incomplete years,
        # so we pass the FULL scored set (includes 2025 score rows = NaN
        # where appropriate) plus the full enriched indicator data.
        render_detail_tab(scored_full, enriched, selections)


if __name__ == "__main__":
    main()
