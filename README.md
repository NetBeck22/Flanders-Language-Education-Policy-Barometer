# Flanders Language & Education Policy Barometer

A longitudinal Streamlit dashboard that monitors the relationship between
the Dutch-language context and educational outcomes across Flemish
municipalities, 2014–2024.

## Quick start

### 1. Install Python 3.10+

Verify in a terminal:

```
py --version
```

If you don't have Python: <https://www.python.org/downloads/>.

### 2. Install the required packages

```
py -m pip install streamlit plotly pandas openpyxl scikit-learn scipy
```

### 3. Run the dashboard

From the project folder, in a terminal:

```
py -m streamlit run app.py
```

A browser tab opens automatically at `http://localhost:8501`.

Stop the server with **Ctrl+C** in the terminal.

---

## What's in this folder

| File                              | What it does                                        |
| --------------------------------- | --------------------------------------------------- |
| `app.py`                          | Streamlit dashboard — main entry point              |
| `config.py`                       | Indicator definitions, province lookup, palettes    |
| `data_loader.py`                  | Reshapes the wide Excel export into tidy long format |
| `compute_scores.py`               | Z-score normalisation + composite scores            |
| `auto_analysis.py`                | Rule-based per-municipality narrative (Tab 5)       |
| `compactere_relatief_DataVis.xlsx`| Source data (provincies.incijfers.be export)        |
| `restructured_data.xlsx`          | Cleaned long-format data (for inspection)           |
| `.streamlit/config.toml`          | Forces a light theme                                |

## Tabs overview

- **0. Intro** — what the barometer does and how to read it
- **1. Dutch Language Pressure** — distribution, evolution, animated ranking
- **2. Educational Strain** — same structure for the outcome score
- **3. Scatter** — both scores; OLS regression + means update per year
- **4. Trend & Deviation** — OLS residuals over time, baseline selectable
- **5. Municipal Detail** — raw indicators (vs Flemish average), radar,
  auto-generated summary per selected municipality, downloadable CSV

## Notes for the recipient

- Scores are z-score normalised **within each year**: values are
  comparable across municipalities in the same year, but not across
  years.
- 2025 is excluded from score-based tabs because two component
  indicators are not yet published.
- Use the sidebar's *Brussels-Capital toggle* to switch between
  "all 304 municipalities" and "five Flemish provinces only".

## Troubleshooting

- **"Python is niet gevonden"** on Windows: install Python from
  python.org or run via `py.exe` instead of `python`.
- **Streamlit deprecation warning** about `use_container_width`: harmless,
  appears with older Streamlit versions.
- **Charts not updating after toggling sidebar**: refresh the browser
  tab (F5) or press **R** while focused on the app.
