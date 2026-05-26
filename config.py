"""
Configuration for the Flemish municipalities policy barometer.

Single source of truth for:
- the source Excel file path
- indicator definitions (raw column header -> short internal key)
- which indicators feed which composite score
- the gemeente -> provincie lookup

Adding a new yearly slice does NOT require editing this file.
Adding a new indicator does: append it to INDICATOR_LABELS and (if relevant)
to LANGUAGE_PRESSURE_COMPONENTS or EDUCATIONAL_OUTCOME_COMPONENTS.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# File location
# ---------------------------------------------------------------------------

DATA_FILE = Path(__file__).parent / "compactere_relatief_DataVis.xlsx"

# ---------------------------------------------------------------------------
# Indicator mapping
#
# Keys are short internal identifiers used throughout the code base.
# Values are the literal indicator labels as they appear in row 1 of the
# raw Excel export (provincies.incijfers.be wide format).
#
# If the upstream label ever changes, update it here and nothing else needs
# to change.
# ---------------------------------------------------------------------------

INDICATOR_LABELS = {
    "pct_nl_primary": (
        "leerlingen basisonderwijs die thuis geen Nederlands spreken "
        "(t.o.v. lln bo) - WP [%]"
    ),
    "pct_nl_secondary": (
        "leerlingen secundair onderwijs die thuis geen Nederlands spreken "
        "(t.o.v. lln so) - WP [%]"
    ),
    "newcomers_per_1000_adults": (
        "nieuwkomers per 1.000 inwoners 18+ jaar [‰]"
    ),
    "pct_repeaters_primary": (
        "zittenblijvers lager onderwijs "
        "(t.o.v. leerlingen lager onderwijs) - WP [%]"
    ),
    "enrollment_rate_primary": (
        "inschrijvingsgraad in Vlaams onderwijs: basisschoolleeftijd "
        "(3-11 jaar) - WP [ratio]"
    ),
    "pct_delay_primary": (
        "leerlingen lager onderwijs met één jaar of meer schoolse "
        "vertraging (t.o.v. lln lo) - WP [%]"
    ),
    "pct_delay_secondary": (
        "leerlingen secundair onderwijs met twee jaar of meer schoolse "
        "vertraging (t.o.v. lln so) - WP [%]"
    ),
    "pct_repeaters_secondary": (
        "zittenblijvers secundair onderwijs "
        "(t.o.v. leerlingen secundair onderwijs) - WP [%]"
    ),
    "enrollment_rate_secondary": (
        "inschrijvingsgraad in Vlaams onderwijs: secundaire "
        "schoolleeftijd (12-17 jaar) - WP [ratio]"
    ),
    "pct_early_school_leavers": (
        "vroegtijdige schoolverlaters (t.o.v. schoolverlaters) - WP [%]"
    ),
}

# Human-readable English labels shown in the dashboard UI.
INDICATOR_DISPLAY = {
    "pct_nl_primary":
        "% primary pupils not speaking Dutch at home",
    "pct_nl_secondary":
        "% secondary pupils not speaking Dutch at home",
    "newcomers_per_1000_adults":
        "Newcomers per 1 000 adults (18+)",
    "pct_repeaters_primary":
        "% grade repeaters (primary)",
    "enrollment_rate_primary":
        "Enrollment rate, primary school age (3-11)",
    "pct_delay_primary":
        "% pupils with 1+ year delay (primary)",
    "pct_delay_secondary":
        "% pupils with 2+ year delay (secondary)",
    "pct_repeaters_secondary":
        "% grade repeaters (secondary)",
    "enrollment_rate_secondary":
        "Enrollment rate, secondary school age (12-17)",
    "pct_early_school_leavers":
        "% early school leavers",
}

# Display scaling per indicator.
#
# The source Excel stores some percentage-like indicators as a FRACTION
# (0-1, e.g. 0.238 means 23.8 %) while others are already on a 0-100
# scale or use per-mille units. To present numbers consistently to
# policy-makers, the dashboard scales each indicator on display only
# (no impact on score calculations, which use z-scores anyway).
#
# Format: indicator_key -> (multiplier, unit_suffix)
INDICATOR_DISPLAY_SCALE = {
    # Fraction (0-1) -> show as percent.
    "pct_nl_primary":            (100.0, "%"),
    "pct_nl_secondary":          (100.0, "%"),
    "pct_repeaters_primary":     (100.0, "%"),
    "pct_repeaters_secondary":   (100.0, "%"),
    "pct_delay_primary":         (100.0, "%"),
    "pct_delay_secondary":       (100.0, "%"),
    "pct_early_school_leavers":  (100.0, "%"),
    # Already on 0-100 scale -> leave as-is, just add "%".
    "enrollment_rate_primary":   (1.0, "%"),
    "enrollment_rate_secondary": (1.0, "%"),
    "enrollment_rate_avg":       (1.0, "%"),
    # Per-mille unit -> leave as-is with the per-mille sign.
    "newcomers_per_1000_adults": (1.0, "‰"),
}

# Short tooltip text shown next to chart titles.
INDICATOR_TOOLTIP = {
    "pct_nl_primary":
        "Share of pupils in primary education who do not speak Dutch at home.",
    "pct_nl_secondary":
        "Share of pupils in secondary education who do not speak Dutch at home.",
    "newcomers_per_1000_adults":
        "Number of newcomers (new arrivals) per 1 000 adult residents (18+).",
    "pct_repeaters_primary":
        "Share of primary-school pupils repeating their current grade.",
    "enrollment_rate_primary":
        "Share of primary-school-aged children enrolled in Flemish education.",
    "pct_delay_primary":
        "Share of primary pupils with at least one year of school delay.",
    "pct_delay_secondary":
        "Share of secondary pupils with two or more years of school delay.",
    "pct_repeaters_secondary":
        "Share of secondary pupils repeating their current grade.",
    "enrollment_rate_secondary":
        "Share of secondary-school-aged adolescents enrolled in Flemish education.",
    "pct_early_school_leavers":
        "Share of school leavers who left without a qualifying diploma.",
}

# ---------------------------------------------------------------------------
# Composite-score definitions
#
# Each component is a dict with:
#   key   -> internal indicator key (must exist in INDICATOR_LABELS)
#   sign  -> +1 if higher raw value = higher score
#            -1 if higher raw value = lower score (reverse before averaging)
#   cap   -> optional numeric cap applied before sign-flip (e.g. 100 for rates)
# ---------------------------------------------------------------------------

LANGUAGE_PRESSURE_COMPONENTS = [
    {"key": "pct_nl_primary",            "sign": +1, "cap": None},
    {"key": "pct_nl_secondary",          "sign": +1, "cap": None},
    {"key": "newcomers_per_1000_adults", "sign": +1, "cap": None},
]

# For Educational Strain:
#   - Delay: primary 1+ year delay (most literal match to spec wording)
#   - Early school leaving
#   - Enrollment rate: averaged primary + secondary, capped at 100, then
#     reversed (sign = -1) so that LOW enrollment = HIGH outcome-pressure score
#
# The averaging is handled in compute_scores.py by listing both enrollment
# entries as separate components and dividing the average by 2 conceptually;
# practically we list the *averaged* derived indicator below — see
# compute_scores.derive_helper_indicators.
EDUCATIONAL_OUTCOME_COMPONENTS = [
    # Secondary delay (2+ years) is preferred over primary delay because a
    # pupil who reaches secondary with 2+ years of delay was typically
    # already lagging in primary — so this indicator partly captures
    # earlier accumulation as well, without double-counting it in the
    # composite.
    {"key": "pct_delay_secondary",       "sign": +1, "cap": None},
    {"key": "pct_early_school_leavers",  "sign": +1, "cap": None},
    {"key": "enrollment_rate_avg",       "sign": -1, "cap": 100.0},
]

# Derived indicators are computed in code (compute_scores.py) before scoring.
# Add a label here so the UI can display them.
INDICATOR_DISPLAY["enrollment_rate_avg"] = "Average enrollment rate (3-17)"
INDICATOR_TOOLTIP["enrollment_rate_avg"] = (
    "Average of the primary (3-11) and secondary (12-17) enrollment rates. "
    "Capped at 100 and reversed in the composite score so that low enrollment "
    "contributes to a worse Educational Strain Score."
)

# ---------------------------------------------------------------------------
# Score interpretation (used as tooltips / captions in the dashboard)
# ---------------------------------------------------------------------------

SCORE_LABELS = {
    "language_pressure_score": "Dutch Language Pressure Score",
    "educational_outcome_score": "Educational Strain Score",
}

SCORE_DESCRIPTIONS = {
    "language_pressure_score": (
        "Composite score of Dutch-language-context pressure in a "
        "municipality. Higher = more pupils not speaking Dutch at home "
        "(in **both** primary **and** secondary education) and/or more "
        "adult newcomers, relative to other municipalities in the same "
        "year.\n\n"
        "*Why include newcomers?* The two pupil-level indicators capture "
        "the **current** language situation in classrooms. The "
        "newcomers-per-1 000-adults indicator is added as a **leading "
        "proxy for future language pressure**: today's adult newcomers "
        "are tomorrow's pupil parents, and concentrations of new arrivals "
        "predict how the language composition of the school population "
        "will evolve over the next 3-10 years. Including it lets "
        "policy-makers anticipate rather than only react.\n\n"
        "**Formula** — for every municipality *m* and year *y*:\n\n"
        "$$\\text{DutchLangPressure}_{m,y} \\;=\\; "
        "\\frac{1}{3}\\,\\Big( "
        "z(\\text{\\%NL}^{\\text{primary}}_{m,y}) \\;+\\; "
        "z(\\text{\\%NL}^{\\text{secondary}}_{m,y}) \\;+\\; "
        "z(\\text{newcomers per 1 000 adults}_{m,y}) "
        "\\Big)$$\n\n"
        "where $z(\\cdot)$ standardises each indicator **within year *y*** "
        "across all Flemish municipalities (mean 0, standard deviation 1), so "
        "scores are comparable between municipalities in the same year."
    ),
    "educational_outcome_score": (
        "Composite score of educational-outcome strain. "
        "Higher = more secondary-school **delay** (2+ years), more "
        "**early school leavers**, and/or **lower enrollment** (averaged "
        "over primary *and* secondary school age), relative to other "
        "municipalities in the same year.\n\n"
        "*Note:* secondary delay is preferred over primary delay because "
        "pupils who reach secondary with 2+ years of delay typically "
        "started accumulating that delay already in primary — so this "
        "indicator partly captures the earlier school career too.\n\n"
        "**Formula** — for every municipality *m* and year *y*:\n\n"
        "$$\\text{EducationalStrain}_{m,y} \\;=\\; "
        "\\frac{1}{3}\\,\\Big( "
        "z(\\text{\\%delay}^{\\text{secondary,\\;2+yr}}_{m,y}) \\;+\\; "
        "z(\\text{\\%early leavers}_{m,y}) \\;-\\; "
        "z(\\overline{\\text{enrollment}}^{\\,3\\text{-}17}_{m,y}\\,|_{\\le 100}) "
        "\\Big)$$\n\n"
        "where $z(\\cdot)$ standardises each indicator **within year *y*** "
        "across all Flemish municipalities (mean 0, standard deviation 1) "
        "and $\\overline{\\text{enrollment}}^{\\,3\\text{-}17}$ is the "
        "average of the primary (3-11) and secondary (12-17) enrollment "
        "rates, **capped at 100** before standardising. The minus sign "
        "reverses enrollment so that *lower* enrollment contributes to a "
        "*higher* strain score, in line with the other two components."
    ),
}

# Scores are normalised within each year separately, so absolute values are
# comparable ACROSS municipalities WITHIN a year, but NOT directly across
# years. The dashboard surfaces this caveat in every relevant chart.
SCORE_CAVEAT = (
    "Scores are z-score normalised within each year. "
    "Compare municipalities within a year; trends over time show relative "
    "position, not absolute change."
)

# ---------------------------------------------------------------------------
# Province lookup
#
# Built from the 312 unique row labels in the raw export. Brussels-Capital
# municipalities are grouped under 'Brussel (gewest)'. Rows that are
# bookkeeping artefacts (export date, "not localisable", etc.) are listed
# in HOUSEKEEPING_ROWS so the loader can drop them.
# ---------------------------------------------------------------------------

PROVINCE_BY_MUNICIPALITY = {
    # ---- Antwerpen ----
    "Aartselaar": "Antwerpen", "Antwerpen": "Antwerpen", "Arendonk": "Antwerpen",
    "Baarle-Hertog": "Antwerpen", "Balen": "Antwerpen", "Beerse": "Antwerpen",
    "Berlaar": "Antwerpen", "Boechout": "Antwerpen", "Bonheiden": "Antwerpen",
    "Boom": "Antwerpen", "Bornem": "Antwerpen", "Brasschaat": "Antwerpen",
    "Brecht": "Antwerpen", "Dessel": "Antwerpen", "Duffel": "Antwerpen",
    "Edegem": "Antwerpen", "Essen": "Antwerpen", "Geel": "Antwerpen",
    "Grobbendonk": "Antwerpen", "Heist-op-den-Berg": "Antwerpen",
    "Hemiksem": "Antwerpen", "Herentals": "Antwerpen", "Herenthout": "Antwerpen",
    "Herselt": "Antwerpen", "Hoogstraten": "Antwerpen", "Hove": "Antwerpen",
    "Hulshout": "Antwerpen", "Kalmthout": "Antwerpen", "Kapellen": "Antwerpen",
    "Kasterlee": "Antwerpen", "Kontich": "Antwerpen", "Laakdal": "Antwerpen",
    "Lier": "Antwerpen", "Lille": "Antwerpen", "Lint": "Antwerpen",
    "Malle": "Antwerpen", "Mechelen": "Antwerpen", "Meerhout": "Antwerpen",
    "Merksplas": "Antwerpen", "Mol": "Antwerpen", "Mortsel": "Antwerpen",
    "Niel": "Antwerpen", "Nijlen": "Antwerpen", "Olen": "Antwerpen",
    "Oud-Turnhout": "Antwerpen", "Putte": "Antwerpen",
    "Puurs-Sint-Amands": "Antwerpen", "Ranst": "Antwerpen",
    "Ravels": "Antwerpen", "Retie": "Antwerpen", "Rijkevorsel": "Antwerpen",
    "Rumst": "Antwerpen", "Schelle": "Antwerpen", "Schilde": "Antwerpen",
    "Schoten": "Antwerpen", "Sint-Katelijne-Waver": "Antwerpen",
    "Stabroek": "Antwerpen", "Turnhout": "Antwerpen", "Vorselaar": "Antwerpen",
    "Vosselaar": "Antwerpen", "Westerlo": "Antwerpen", "Wijnegem": "Antwerpen",
    "Willebroek": "Antwerpen", "Wommelgem": "Antwerpen",
    "Wuustwezel": "Antwerpen", "Zandhoven": "Antwerpen", "Zoersel": "Antwerpen",

    # ---- Limburg ----
    "Alken": "Limburg", "As": "Limburg", "Beringen": "Limburg",
    "Bilzen-Hoeselt": "Limburg", "Bocholt": "Limburg", "Bree": "Limburg",
    "Diepenbeek": "Limburg", "Dilsen-Stokkem": "Limburg", "Genk": "Limburg",
    "Gingelom": "Limburg", "Halen": "Limburg", "Hamont-Achel": "Limburg",
    "Hasselt": "Limburg", "Hechtel-Eksel": "Limburg", "Heers": "Limburg",
    "Herk-de-Stad": "Limburg", "Heusden-Zolder": "Limburg",
    "Houthalen-Helchteren": "Limburg", "Kinrooi": "Limburg",
    "Lanaken": "Limburg", "Leopoldsburg": "Limburg", "Lommel": "Limburg",
    "Lummen": "Limburg", "Maaseik": "Limburg", "Maasmechelen": "Limburg",
    "Nieuwerkerken": "Limburg", "Oudsbergen": "Limburg", "Peer": "Limburg",
    "Pelt": "Limburg", "Riemst": "Limburg", "Sint-Truiden": "Limburg",
    "Tessenderlo-Ham": "Limburg", "Tongeren-Borgloon": "Limburg",
    "Voeren": "Limburg", "Wellen": "Limburg", "Zonhoven": "Limburg",
    "Zutendaal": "Limburg",

    # ---- Oost-Vlaanderen ----
    "Aalst": "Oost-Vlaanderen", "Aalter": "Oost-Vlaanderen",
    "Assenede": "Oost-Vlaanderen", "Berlare": "Oost-Vlaanderen",
    "Beveren-Kruibeke-Zwijndrecht": "Oost-Vlaanderen",
    "Brakel": "Oost-Vlaanderen", "Buggenhout": "Oost-Vlaanderen",
    "Deinze": "Oost-Vlaanderen", "Denderleeuw": "Oost-Vlaanderen",
    "Dendermonde": "Oost-Vlaanderen", "Destelbergen": "Oost-Vlaanderen",
    "Eeklo": "Oost-Vlaanderen", "Erpe-Mere": "Oost-Vlaanderen",
    "Evergem": "Oost-Vlaanderen", "Gavere": "Oost-Vlaanderen",
    "Geraardsbergen": "Oost-Vlaanderen", "Gent": "Oost-Vlaanderen",
    "Haaltert": "Oost-Vlaanderen", "Hamme": "Oost-Vlaanderen",
    "Herzele": "Oost-Vlaanderen", "Horebeke": "Oost-Vlaanderen",
    "Kaprijke": "Oost-Vlaanderen", "Kluisbergen": "Oost-Vlaanderen",
    "Kruisem": "Oost-Vlaanderen", "Laarne": "Oost-Vlaanderen",
    "Lebbeke": "Oost-Vlaanderen", "Lede": "Oost-Vlaanderen",
    "Lierde": "Oost-Vlaanderen",
    "Lievegem": "Oost-Vlaanderen", "Lochristi": "Oost-Vlaanderen",
    "Lokeren": "Oost-Vlaanderen", "Maarkedal": "Oost-Vlaanderen",
    "Maldegem": "Oost-Vlaanderen", "Merelbeke-Melle": "Oost-Vlaanderen",
    "Nazareth-De Pinte": "Oost-Vlaanderen", "Ninove": "Oost-Vlaanderen",
    "Oosterzele": "Oost-Vlaanderen", "Oudenaarde": "Oost-Vlaanderen",
    "Ronse": "Oost-Vlaanderen", "Sint-Gillis-Waas": "Oost-Vlaanderen",
    "Sint-Laureins": "Oost-Vlaanderen",
    "Sint-Lievens-Houtem": "Oost-Vlaanderen",
    "Sint-Martens-Latem": "Oost-Vlaanderen", "Sint-Niklaas": "Oost-Vlaanderen",
    "Stekene": "Oost-Vlaanderen", "Temse": "Oost-Vlaanderen",
    "Waasmunster": "Oost-Vlaanderen", "Wetteren": "Oost-Vlaanderen",
    "Wichelen": "Oost-Vlaanderen", "Wortegem-Petegem": "Oost-Vlaanderen",
    "Zele": "Oost-Vlaanderen", "Zelzate": "Oost-Vlaanderen",
    "Zottegem": "Oost-Vlaanderen", "Zulte": "Oost-Vlaanderen",
    "Zwalm": "Oost-Vlaanderen",

    # ---- Vlaams-Brabant ----
    "Aarschot": "Vlaams-Brabant", "Affligem": "Vlaams-Brabant",
    "Asse": "Vlaams-Brabant", "Begijnendijk": "Vlaams-Brabant",
    "Bekkevoort": "Vlaams-Brabant", "Beersel": "Vlaams-Brabant",
    "Bertem": "Vlaams-Brabant", "Bever": "Vlaams-Brabant",
    "Bierbeek": "Vlaams-Brabant",
    "Boortmeerbeek": "Vlaams-Brabant", "Boutersem": "Vlaams-Brabant",
    "Diest": "Vlaams-Brabant", "Dilbeek": "Vlaams-Brabant",
    "Drogenbos": "Vlaams-Brabant", "Geetbets": "Vlaams-Brabant",
    "Glabbeek": "Vlaams-Brabant", "Grimbergen": "Vlaams-Brabant",
    "Haacht": "Vlaams-Brabant", "Halle": "Vlaams-Brabant",
    "Herent": "Vlaams-Brabant", "Hoegaarden": "Vlaams-Brabant",
    "Hoeilaart": "Vlaams-Brabant", "Holsbeek": "Vlaams-Brabant",
    "Huldenberg": "Vlaams-Brabant", "Kampenhout": "Vlaams-Brabant",
    "Kapelle-op-den-Bos": "Vlaams-Brabant", "Keerbergen": "Vlaams-Brabant",
    "Kortenaken": "Vlaams-Brabant", "Kortenberg": "Vlaams-Brabant",
    "Kraainem": "Vlaams-Brabant", "Landen": "Vlaams-Brabant",
    "Lennik": "Vlaams-Brabant", "Leuven": "Vlaams-Brabant",
    "Liedekerke": "Vlaams-Brabant", "Linkebeek": "Vlaams-Brabant",
    "Linter": "Vlaams-Brabant", "Londerzeel": "Vlaams-Brabant",
    "Lubbeek": "Vlaams-Brabant", "Machelen": "Vlaams-Brabant",
    "Meise": "Vlaams-Brabant", "Merchtem": "Vlaams-Brabant",
    "Opwijk": "Vlaams-Brabant", "Oud-Heverlee": "Vlaams-Brabant",
    "Overijse": "Vlaams-Brabant", "Pajottegem": "Vlaams-Brabant",
    "Pepingen": "Vlaams-Brabant", "Roosdaal": "Vlaams-Brabant",
    "Rotselaar": "Vlaams-Brabant",
    "Scherpenheuvel-Zichem": "Vlaams-Brabant",
    "Sint-Genesius-Rode": "Vlaams-Brabant",
    "Sint-Pieters-Leeuw": "Vlaams-Brabant",
    "Steenokkerzeel": "Vlaams-Brabant", "Ternat": "Vlaams-Brabant",
    "Tervuren": "Vlaams-Brabant", "Tielt-Winge": "Vlaams-Brabant",
    "Tienen": "Vlaams-Brabant", "Tremelo": "Vlaams-Brabant",
    "Vilvoorde": "Vlaams-Brabant", "Wemmel": "Vlaams-Brabant",
    "Wezembeek-Oppem": "Vlaams-Brabant", "Zaventem": "Vlaams-Brabant",
    "Zemst": "Vlaams-Brabant", "Zoutleeuw": "Vlaams-Brabant",

    # ---- West-Vlaanderen ----
    "Alveringem": "West-Vlaanderen", "Anzegem": "West-Vlaanderen",
    "Ardooie": "West-Vlaanderen", "Avelgem": "West-Vlaanderen",
    "Beernem": "West-Vlaanderen", "Blankenberge": "West-Vlaanderen",
    "Bredene": "West-Vlaanderen", "Brugge": "West-Vlaanderen",
    "Damme": "West-Vlaanderen", "De Haan": "West-Vlaanderen",
    "De Panne": "West-Vlaanderen", "Deerlijk": "West-Vlaanderen",
    "Dentergem": "West-Vlaanderen", "Diksmuide": "West-Vlaanderen",
    "Gistel": "West-Vlaanderen", "Harelbeke": "West-Vlaanderen",
    "Heuvelland": "West-Vlaanderen", "Hooglede": "West-Vlaanderen",
    "Houthulst": "West-Vlaanderen", "Ichtegem": "West-Vlaanderen",
    "Ieper": "West-Vlaanderen", "Ingelmunster": "West-Vlaanderen",
    "Izegem": "West-Vlaanderen", "Jabbeke": "West-Vlaanderen",
    "Knokke-Heist": "West-Vlaanderen", "Koekelare": "West-Vlaanderen",
    "Koksijde": "West-Vlaanderen", "Kortemark": "West-Vlaanderen",
    "Kortrijk": "West-Vlaanderen", "Kuurne": "West-Vlaanderen",
    "Langemark-Poelkapelle": "West-Vlaanderen",
    "Ledegem": "West-Vlaanderen", "Lendelede": "West-Vlaanderen",
    "Lichtervelde": "West-Vlaanderen", "Lo-Reninge": "West-Vlaanderen",
    "Menen": "West-Vlaanderen", "Mesen": "West-Vlaanderen",
    "Middelkerke": "West-Vlaanderen", "Moorslede": "West-Vlaanderen",
    "Nieuwpoort": "West-Vlaanderen", "Oostende": "West-Vlaanderen",
    "Oostkamp": "West-Vlaanderen", "Oostrozebeke": "West-Vlaanderen",
    "Oudenburg": "West-Vlaanderen", "Pittem": "West-Vlaanderen",
    "Poperinge": "West-Vlaanderen", "Roeselare": "West-Vlaanderen",
    "Spiere-Helkijn": "West-Vlaanderen", "Staden": "West-Vlaanderen",
    "Tielt": "West-Vlaanderen", "Torhout": "West-Vlaanderen",
    "Veurne": "West-Vlaanderen", "Vleteren": "West-Vlaanderen",
    "Waregem": "West-Vlaanderen", "Wervik": "West-Vlaanderen",
    "Wevelgem": "West-Vlaanderen", "Wielsbeke": "West-Vlaanderen",
    "Wingene": "West-Vlaanderen", "Zedelgem": "West-Vlaanderen",
    "Zonnebeke": "West-Vlaanderen", "Zuienkerke": "West-Vlaanderen",
    "Zwevegem": "West-Vlaanderen",

    # ---- Brussels-Capital (kept for completeness; can be filtered out) ----
    "Anderlecht": "Brussel (gewest)", "Brussel": "Brussel (gewest)",
    "Elsene": "Brussel (gewest)", "Etterbeek": "Brussel (gewest)",
    "Evere": "Brussel (gewest)", "Ganshoren": "Brussel (gewest)",
    "Jette": "Brussel (gewest)", "Koekelberg": "Brussel (gewest)",
    "Oudergem": "Brussel (gewest)", "Schaarbeek": "Brussel (gewest)",
    "Sint-Agatha-Berchem": "Brussel (gewest)",
    "Sint-Gillis": "Brussel (gewest)",
    "Sint-Jans-Molenbeek": "Brussel (gewest)",
    "Sint-Joost-ten-Node": "Brussel (gewest)",
    "Sint-Lambrechts-Woluwe": "Brussel (gewest)",
    "Sint-Pieters-Woluwe": "Brussel (gewest)",
    "Ukkel": "Brussel (gewest)", "Vorst": "Brussel (gewest)",
    "Watermaal-Bosvoorde": "Brussel (gewest)",

    # ---- Herstappe (Limburg) — separate to ensure inclusion ----
    "Herstappe": "Limburg",
}

# Ordered list of the five Flemish provinces (handy for filters / colour scales)
FLEMISH_PROVINCES = [
    "Antwerpen",
    "Limburg",
    "Oost-Vlaanderen",
    "Vlaams-Brabant",
    "West-Vlaanderen",
]

# Rows in column A of the raw export that are NOT municipalities. The loader
# drops these silently.
HOUSEKEEPING_ROWS = {
    "Bron",
    "Buiten Vlaanderen en Brussel",
    "Datum export",
    "Niet te lokaliseren",
    "Niet te lokaliseren - Brussel",
    "Niet te lokaliseren - Vlaanderen",
    "Speciale waarden",
    "provincies.incijfers.be",
}

# ---------------------------------------------------------------------------
# Plot styling
# ---------------------------------------------------------------------------

# Neutral grey for "context" municipalities when at least one is highlighted.
GREY_COLOR = "#D3D3D3"

# Default province colour palette.
PROVINCE_PALETTE_DEFAULT = {
    "Antwerpen":        "#1f77b4",
    "Limburg":          "#2ca02c",
    "Oost-Vlaanderen":  "#ff7f0e",
    "Vlaams-Brabant":   "#9467bd",
    "West-Vlaanderen":  "#d62728",
    "Brussel (gewest)": "#7f7f7f",
}

# Colour-blind-safe province palette (Wong 2011, Nature Methods 8:441).
# All six hues remain distinguishable under protanopia, deuteranopia and
# tritanopia. The red/green pair of the default palette (West-Vlaanderen
# / Limburg) is replaced by vermillion + bluish-green, which look
# similar to normal vision but differ in luminance and blue/yellow
# components — so they stay separable for the ~8 % of (male) viewers
# with red-green deficiency.
PROVINCE_PALETTE_COLORBLIND = {
    "Antwerpen":        "#0072B2",  # blue
    "Limburg":          "#009E73",  # bluish green
    "Oost-Vlaanderen":  "#E69F00",  # orange
    "Vlaams-Brabant":   "#CC79A7",  # reddish purple
    "West-Vlaanderen":  "#D55E00",  # vermillion
    "Brussel (gewest)": "#56B4E9",  # sky blue
}

# Active palette — mutated in place at the start of every run from
# st.session_state so all chart builders that read PROVINCE_PALETTE[...]
# see the user's current choice without needing to pass the palette as
# an explicit parameter through every function signature.
PROVINCE_PALETTE = dict(PROVINCE_PALETTE_DEFAULT)

# Friendly names shown in the sidebar selector.
PROVINCE_PALETTES = {
    "Default":            PROVINCE_PALETTE_DEFAULT,
    "Colour-blind safe":  PROVINCE_PALETTE_COLORBLIND,
}

# Flemish municipalities that host one of the five main Flemish
# universities. The 'newcomers per 1 000 adults' indicator in these
# municipalities is heavily inflated by international students and
# academic staff who are not the policy target of NT2/OKAN integration
# measures. The auto-analysis flags this so policy-makers don't
# over-attribute language pressure to permanent residency dynamics.
#
# Scope: four official 'universiteitssteden' (Leuven, Gent, Antwerpen,
# Hasselt) + Diepenbeek (UHasselt's main campus sits there) + Elsene
# (VUB's main campus in the Brussels-Capital Region). Hogescholen-only
# cities (Brugge, Kortrijk, Mechelen, Geel) are deliberately NOT in this
# set: their student populations are smaller and more local, so the
# newcomers-inflation effect is much weaker.
STUDENT_CITIES = {
    "Leuven",      # KU Leuven, ~60 000 students
    "Gent",        # UGent, ~50 000 students
    "Antwerpen",   # UAntwerpen, ~25 000 students
    "Hasselt",     # UHasselt (registered seat)
    "Diepenbeek",  # UHasselt main campus
    "Elsene",      # VUB main campus (Brussels-Capital)
}

# Per-municipality palette used in BOTH the Tab 4 residual chart and the
# Tab 5 raw-indicator / radar views. The same alphabetical assignment is
# applied in both places so a given municipality keeps the same colour
# across the two tabs.
#
# Both variants deliberately exclude red and green because Tab 4 has a
# 'better / worse' callout pair in those colours; using red/green for
# per-municipality lines would conflict with that legend.

# Default variant: Tableau-derived hues, distinguishable for full colour
# vision; some pairs (purple/pink, blue/cyan) can blur for the strongest
# colour-vision deficiencies.
HIGHLIGHT_PALETTE_DEFAULT = [
    "#1f77b4",  # blue
    "#9467bd",  # purple
    "#ff7f0e",  # orange
    "#17becf",  # cyan
    "#e377c2",  # pink
    "#8c564b",  # brown
    "#f7b6d2",  # light pink
    "#aec7e8",  # light blue
]

# Colour-blind safe variant: Wong (2011) + IBM Carbon, every pair stays
# distinguishable under protanopia, deuteranopia and tritanopia. Still
# excludes the pure red and pure green hues that clash with Tab 4's
# 'better / worse' callouts.
HIGHLIGHT_PALETTE_COLORBLIND = [
    "#0072B2",  # blue
    "#E69F00",  # orange
    "#CC79A7",  # reddish purple
    "#56B4E9",  # sky blue
    "#F0E442",  # yellow
    "#8c564b",  # brown
    "#785EF0",  # violet (IBM Carbon)
    "#FFB000",  # amber (IBM Carbon)
]

# Active palette — like PROVINCE_PALETTE, mutated in place at the start
# of every run from st.session_state["palette_choice"].
HIGHLIGHT_PALETTE = list(HIGHLIGHT_PALETTE_DEFAULT)

HIGHLIGHT_PALETTES = {
    "Default":            HIGHLIGHT_PALETTE_DEFAULT,
    "Colour-blind safe":  HIGHLIGHT_PALETTE_COLORBLIND,
}
