# Alignment of the dashboard with the course material

Self-reflection mapping the **Flanders Language & Education Policy
Barometer** onto the principles taught in the *Data Visualization* and
*DataVis – Digital Humanities* lectures (Verbert, De Croon, Vande Moere,
Cazacu). Per principle: **how the dashboard implements it** and **where
it deliberately compromises or falls short**.

---

## 1. Few's definition of a dashboard

> "A visual display of the most important information needed to achieve
> one or more objectives, consolidated on a single screen so the
> information can be monitored at a glance." — Stephen Few

| Few's characteristic | Status |
|---|---|
| Visual display | ✅ Plotly + Streamlit |
| Specific objectives | ✅ Long-term monitoring of language vs. educational outcomes |
| Single screen | ⚠️ **Tabs are used instead of a single screen.** Conscious choice: 5 tabs separate concerns and prevent fragmentation within a tab. Few criticises *fragmented* multi-screen designs that hide relationships; here the relationships live within each tab (distribution + ranking + evolution per score; scatter + OLS for cross-score). |
| Monitor at a glance | ✅ Tab 0 (Intro) explains the two top-line scores in one screen; Tabs 1–4 each present one comparative view. |
| Concise, clear, intuitive | ✅ Plain-English titles, tooltips, captions; no Dutch jargon in chart labels. |
| Customised for audience | ✅ Policy-makers and analysts — see *target audience* section in `README.md`. |

---

## 2. Few's "13 common mistakes" — checked one by one

| # | Mistake | Status in this dashboard |
|---|---|---|
| 1 | Exceeding boundaries of a single screen | ⚠️ Tabs (see above). Within each tab the screen is reasonably self-contained. |
| 2 | Inadequate context | ✅ Every chart frames a value: KDE curves per province, Flanders average dashed line, ranking with municipality position, OLS regression with means in the scatter, residual symmetric scale. |
| 3 | Excessive detail / precision | ✅ Scores rounded to two decimals. Tooltips show three at most. No "0.5673829" anywhere. |
| 4 | Deficient measure | ✅ Z-score composites are **purpose-built** for the policy question (a single number that ranks municipalities within a year on Dutch-language pressure / educational strain). Formula is shown in the UI. |
| 5 | Inappropriate display media | ✅ Bar chart for rankings; KDE/line for distributions and trends; scatter for two continuous variables; **no pie charts, no 3D, no gauges**. |
| 6 | Meaningless variety | ✅ Each chart type maps to a clear question; the *same* chart pattern is reused across Tab 1 and Tab 2 (distribution / evolution / animated ranking). |
| 7 | Poorly designed media | ✅ Plotly defaults plus deliberate cleanup (e.g. hidden x-axis when score is also in the bar text). |
| 8 | Inaccurate encoding | ✅ Cleveland-McGill: position (scatter, KDE), length (bars), hue (province) — top-of-ranking encodings. |
| 9 | Arranging the data poorly | ✅ Most important data is up front: scores top of each tab, ranking below, detail in Tab 5. |
| 10 | Highlighting ineffectively / not at all | ✅ Explicit "highlight + context" pattern via opacity + colour, persistent across tabs in `st.session_state`. |
| 11 | Useless decoration | ✅ Light theme, muted grids, no logos, no faux gauges, no drop shadows. |
| 12 | Misusing colour | ⚠️ Province palette uses red (West-Vlaanderen) and green (Limburg), which can be confusing for the ~8 % of (male) viewers with red-green deficiency. **Partial mitigation**: in Tab 4 the per-municipality residual lines deliberately avoid red and green (see `HIGHLIGHT_PALETTE` in `config.py`). Province choice predates this insight — a future iteration could swap to a ColorBrewer Set2 palette. |
| 13 | Unattractive visual design | ✅ Light background, consistent typography, white space, no clutter. |

---

## 3. Cleveland-McGill / Mackinlay encoding ranking

The most accurate visual encodings for quantitative data are *position
on a common scale*, then *length*, then *angle / area*. The dashboard
uses:

- **Position** for both composite scores (scatter, KDE x-axis, line charts) — best.
- **Length** for rankings (horizontal bars) — second best.
- **Colour hue** strictly for **categorical** information (province).
- **Colour intensity / opacity** for the highlight focus pattern.

**Deliberate choice (not a compromise)**: Tab 5 keeps a **radar chart**
for the per-municipality indicator profile.

Few criticises radar mainly when readers must extract *precise values*
— the angle-radius reading is then less accurate than a sorted bar
chart. In this dashboard that's not the radar's job:

- Precise values live in the **auto-analysis text** (positions,
  drivers, residuals) and in the **downloadable CSV table** below the
  radar.
- The radar's job is the **shape-level comparison**: at a glance, does
  municipality A's profile *look* similar to B's, or is it tilted on a
  different axis? Six indicators × up to five municipalities in one
  view, with the same scale per axis, is something a bar grid does
  less compactly.
- The "best of both" combination — narrative + radar shape +
  underlying numbers — is in line with Few's own advice to **support
  meaningful comparisons** and to use **different display media for
  different reading goals**.

The radar is kept as a *visual gestalt* on top of the precise numerical
layers, not as a substitute for them.

---

## 4. Shneiderman's mantra: Overview → Zoom & Filter → Details-on-demand

| Step | Implementation |
|---|---|
| Overview | Tab 0 (intro) and Tabs 1–3 give the population-wide picture per score and per pair of scores. |
| Zoom | Animation slider in Tab 3 (year-by-year); zoom-by-province pill on the ranking; baseline picker in Tab 4. |
| Filter | Brussels-Capital toggle (sidebar), per-tab province pill, multiselect highlight. |
| Details-on-demand | Tab 5: per-municipality narrative, raw indicator line charts vs. Flanders average, radar, downloadable CSV. |

Shneiderman's 7 tasks — additional notes:

- **Relate**: poor man's brushing-and-linking via `st.session_state`
  (the highlight persists across tabs).
- **History**: not implemented (no undo / replay).
- **Extract**: ✅ CSV download in Tab 5.

---

## 5. Yi et al. (2007) — user-intent interaction taxonomy

| Intent | Where it lives |
|---|---|
| Select | Highlight multiselect (sidebar). |
| Explore | Scatter animation; year-by-year ranking. |
| Reconfigure | Province pill on the ranking; baseline pill in Tab 4 (Flanders / per province). |
| Encode | Limited — encodings are fixed per chart. |
| Abstract / Elaborate | "Focus + context": coloured highlighted munis on top of light-grey context; collapsible auto-analysis cards in Tab 5. |
| Filter | Brussels-Capital toggle; province pill. |
| Connect | Persistent highlight links all tabs around the same gemeente set. |

---

## 6. Vande Moere's 10 guidelines

1. **Visualise insights, not data** — ✅ The auto-analysis in Tab 5 is
   explicitly an *insight* layer (position, trend, driver, residual,
   policy advice), not just a re-print of numbers.
2. **Consider data proxies, not data** — ✅ Newcomers per 1 000 adults
   is positioned as a **leading proxy** for future language pressure
   (today's adult newcomers → tomorrow's pupil parents). The intro
   tab and the formula caption explain this explicitly.
3. **Visualise data interpretations** — ✅ Z-score composites,
   OLS residuals, derived enrollment average, student-city caveat — all
   interpretive layers above the raw indicators.
4. **Avoid visualisation pitfalls** — see Few's 13 (above).
5. **Open the design space** — ⚠️ The dashboard is **conventional**
   (bars, KDEs, scatter, lines). No indexical / autographic / artistic
   moves. Defensible for a *policy* audience, but doesn't extend the
   design space the way Lupi/Posavec or Pitch Interactive would.
6. **Engage the user** — ✅ Animated ranking with a true bar-race;
   per-year regression in the scatter; expandable per-municipality
   narrative.
7. **Tell a story** — ✅ Tab 0 sets the frame; the auto-analysis in
   Tab 5 has a fixed three-section structure (Language → Strain →
   Integrated lens) that reads as a mini-argument per municipality.
8. **Be critical** — ✅ Brussels-Capital toggle with explicit warning
   about its impact on the OLS slope; student-city caveat that
   discounts the newcomers indicator for Leuven/Gent/Antwerpen…;
   "interpretation caveats" block in the intro tab.
9. **Show uncertainty** — ⚠️ **Partial.** Year-2025 incompleteness is
   handled (excluded from score views; raw indicators kept where
   available). But **no measurement uncertainty** (confidence intervals
   on z-scores, robust SE on the OLS line) is visualised. This is the
   biggest gap in the current build.
10. **Integrate participation** — N/A for this artefact (one-way
    monitoring tool), not a participatory installation.

---

## 7. Perception (Verbert) — colour, pre-attentive, Gestalt

- **Pre-attentive pop-out** for the highlight: combination of *colour
  hue* + *opacity* + *marker size* makes selected munis stand out
  without needing serial search.
- **Colour roles**:
  - *Hue* → categorical (province).
  - *Opacity / saturation* → focus (highlighted vs context).
  - *Diverging* (RdBu, symmetric around 0) → residuals in Tab 4.
- **Colour-blind safety**:
  - Tab 4 highlight palette **deliberately excludes red and green**
    (see `HIGHLIGHT_PALETTE`), because the surrounding "better / worse"
    callouts already use those colours.
  - Province palette has green/red — see compromise in §2 mistake 12.
- **Gestalt**:
  - *Proximity* → tabs group related charts; the auto-analysis sections
    use vertical proximity within an expander.
  - *Similarity* → the same province colour is reused across the
    evolution chart, KDE, scatter and table.
  - *Closure* / *continuity* → smooth line charts and KDEs read as
    single shapes.
  - *Figure / ground* → low-opacity context vs full-opacity highlight.

---

## 8. Representation (Verbert) — chart-type and convention choices

| Convention | Status |
|---|---|
| Time on x-axis | ✅ Every evolution chart. |
| Bar charts start at zero | ✅ Tab 5 raw indicator charts use `rangemode="tozero"`. The z-score bars in Tab 1/2 start where the data starts because **z = 0 is a meaningful centre**, not an arbitrary zero — Few-style "natural zero" doesn't apply to z-scores. |
| Direct labels > legend | ✅ Municipality names directly on bars in the animated ranking; chart titles describe the metric. Legend used only for the province colour key in the scatter (clickable to toggle). |
| Natural ordering | ✅ Provinces ordered alphabetically Flanders-first, Brussels last. |
| Annotation key parts of the story | ✅ OLS equation + means annotated in the scatter; "Vlaanderen avg" dashed line labelled. |
| Limit number of colours | ✅ 6 province hues + 1 reference (black dashed). |
| Same colour = same data | ✅ Province palette reused across every chart. |
| Save the pies for dessert | ✅ Zero pie charts in the dashboard. |

---

## 9. Pitfalls Vande Moere explicitly warns about

- **Maps without normalisation** — N/A (no choropleth in this build).
- **Equidistant colour ramps** — ✅ Plotly's RdBu (when used) is
  equidistant; the per-municipality `HIGHLIGHT_PALETTE` is categorical
  so equidistance doesn't apply.
- **Spurious correlations** — ⚠️ The OLS line in Tab 3 implies a
  language → outcome relationship. The residual layer in Tab 4
  exposes deviations, and the auto-analysis lens reminds the reader to
  investigate *non-language drivers* when residuals are positive — but
  the dashboard could be more explicit that *correlation ≠ causation*.
- **Lying with visuals** — ✅ All score evolution axes are fixed
  across selections so swapping municipalities never re-scales the
  view; the residual axis is symmetric around zero to give visual
  parity to "better" and "worse".

---

## 10. Where this dashboard *deliberately* compromises

1. **Tabs over single screen.** Five tabs instead of one consolidated
   screen, because five mutually distinct questions cannot be answered
   without fragmenting *somewhere*. Mitigated by persistent highlight
   across tabs.
2. **Province colour palette includes red & green.** Trades colour-
   blind perfection for high-contrast categorical separation. The Tab 4
   highlight palette compensates for the residual chart.
3. **Radar chart in Tab 5.** Kept *deliberately*, not as a concession.
   Used for shape-level comparison of a few municipalities across six
   indicators; precise values come from the surrounding narrative,
   line charts and downloadable table. See §3 for the rationale.
4. **No geographic map.** Considered, declined — would require a
   2025-merged GeoJSON, and the policy questions are mostly answered
   without a spatial dimension. Listed in the intro as a possible
   extension.
5. **No measurement uncertainty.** Z-scores are point estimates; no
   confidence bands. This is the biggest theoretical gap against
   Vande Moere guideline #9.

---

## 11. Concrete future improvements (if continuing)

- **Swap the province palette** to a ColorBrewer **Set2** or **Dark2**
  palette to remove the red/green pair.
- **Add confidence bands** to evolution lines: bootstrap CI per
  province, semi-transparent ribbon under each line.
- **Bring back a Flanders choropleth** in Tab 0 or Tab 3 once a
  2025-merged GeoJSON is available.
- **Add an explicit "correlation ≠ causation" caveat** in Tab 4's
  callout pair to address the spurious-correlation pitfall.
- **Implement an "extract → annotate → share" flow** so a policy-maker
  can pin an insight (Vande Moere #6 "engage the user" + #7 "tell a
  story").

---

## 12. Course-criterion checklist (summary)

| Criterion | Score |
|---|---|
| Visual clarity / interpretability | ✅ |
| Data → insight, not just data → chart | ✅ (auto-analysis) |
| Highlight + context pattern (focus / Gestalt) | ✅ |
| Cleveland-McGill encoding hierarchy | ✅ (mostly position & length) |
| Shneiderman mantra coverage | ✅ |
| Yi user-intent coverage | ✅ (5 of 7) |
| Pre-attentive pop-out for selected | ✅ |
| Colour palette consistency | ✅ |
| Colour-blind safety | ⚠️ partial |
| Data-ink ratio (Tufte) | ✅ |
| Uncertainty | ⚠️ partial (data completeness only) |
| Critical lens (be critical, show caveats) | ✅ |
| Storytelling structure | ✅ (intro + per-muni narrative) |
| Design-space exploration | ⚠️ conventional |
