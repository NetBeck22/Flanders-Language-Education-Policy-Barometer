# Flanders Language & Education Policy Barometer

**Repository description:** An interactive Streamlit dashboard exploring language context and educational outcomes across Flemish municipalities from 2014 to 2024.

The barometer helps policy-makers, researchers, and analysts compare municipal patterns over time. It combines source indicators into two composite measures, visualizes their distributions and trends, and provides municipality-level detail. The dashboard is descriptive: its comparisons and regressions show associations, not causal effects.

## Get started

### Requirements

- Python 3.10 or newer
- The Excel source workbook included in this repository

### Install and run

From the repository folder, create an environment (recommended), install the dependencies, and start the app:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install streamlit plotly pandas numpy openpyxl scipy
python -m streamlit run app.py
```

On Windows, activate the environment with `.venv\\Scripts\\activate` and use `python` for the commands above. Streamlit prints a local URL, usually <http://localhost:8501>, and opens the dashboard in your browser. Stop it with **Ctrl+C** in the terminal.

## Explore the dashboard

- **Intro:** the measures, controls, and guidance for interpreting results.
- **Dutch Language Pressure:** municipal distributions, change over time, and rankings.
- **Educational Strain:** the corresponding views for educational outcomes.
- **Scatter:** the relationship between the two scores, with a descriptive OLS fit; animate across years to compare patterns.
- **Trend & Deviation:** how municipalities differ from the fitted relationship over time, with selectable baselines and trend methods.
- **Municipal Detail:** indicator trends against the Flemish average, a profile chart, an automatically generated summary, and downloadable CSV data.

Use the sidebar to filter provinces and years, highlight municipalities across views, and include or exclude Brussels-Capital.

## How to read the scores

- Each score is standardized separately **within each year**. A score describes a municipality's position relative to other municipalities in that year; score values should not be compared directly across years.
- Score-based views end at **2024** because some component indicators are not available for 2025. Where available, raw indicator data may cover additional years.
- The language-pressure and educational-strain measures are composite summaries of selected indicators. They are not direct measures of individual pupils, schools, or the causal effect of language context on educational outcomes.
- Regression lines and residuals describe statistical patterns in the data. They do not establish that one measure causes another.

## Project files

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit interface, charts, and dashboard layout |
| `config.py` | Indicator definitions, score components, and municipality/province mappings |
| `data_loader.py` | Reads the source workbook and reshapes it for analysis |
| `compute_scores.py` | Builds composite scores and trend calculations |
| `auto_analysis.py` | Generates rule-based municipality summaries |
| `compactere_relatief_DataVis.xlsx` | Source data export from provincies.incijfers.be |
| `THEORY_ALIGNMENT.md` | Notes on visualization principles used in the dashboard |

## Data and methods

The dashboard reads `compactere_relatief_DataVis.xlsx` from the repository root at startup. It reshapes the workbook into municipality, province, indicator, year, and value records, then computes the composite measures from the indicators defined in `config.py`. See that file for the score components and `THEORY_ALIGNMENT.md` for the visualization rationale.
