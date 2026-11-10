"""UN World Population Prospects (via the UN DESA data portal API, token UNPD_API_TOKEN), national, 2015-2030.

What it adds for scale planning:
  births, infant and under-5 mortality, and surviving infants (= births x (1 - IMR/1000), the immunization cohort)
  married women 15-49 (share and number: turns DHS/SHDS 'married women' rates into numbers)
  population by degree of urbanization (cities, towns, rural): the urban/rural split for cost walks
  single-year-of-age bands: school ages 6-13 and 14-18, girls 10-19, women 15-49, under-1, under-5, 6-59 months
  total fertility rate and crude birth rate

WPP national totals differ from WorldPop: these rows never replace or mix with WorldPop's area figures.
WPP 2024 estimates run to 2023; 2024 onward are projections (median variant).
"""

from __future__ import annotations

from collections import defaultdict

from .. import unpd_portal
from ..context import Context
from ..keys import get

MAIN = {57: "births", 22: "infant_mortality_rate", 24: "under5_mortality_rate", 42: "married_women_15_49_share",
        43: "married_women_15_49", 19: "total_fertility_rate", 55: "crude_birth_rate",
        87: "population_by_urbanization", 88: "population_share_by_urbanization"}
UNITS = {"births": "births", "infant_mortality_rate": "per 1,000 live births", "under5_mortality_rate": "per 1,000 live births",
         "married_women_15_49_share": "percent", "married_women_15_49": "women", "total_fertility_rate": "births per woman",
         "crude_birth_rate": "per 1,000 population", "population_by_urbanization": "people",
         "population_share_by_urbanization": "percent"}
DOU = {"Cities": "cities", "Towns": "towns", "Rural": "rural", "Cities and towns": "cities_and_towns", "Total": "total"}
LAST_ESTIMATE_YEAR = 2023
AGE_YEARS = (2025, 2030)


def build(ctx: Context):
    if not get("UNPD_API_TOKEN", "unpd"):
        return [], {"skipped": "UNPD_API_TOKEN not set"}
    loc = ctx.country.m49
    main = unpd_portal.data(ctx.fetcher, list(MAIN), [loc], 2015, 2030)
    ages = unpd_portal.data(ctx.fetcher, [47], [loc], *AGE_YEARS)
    base = {"area_id": ctx.national_id, "iso3": ctx.country.iso3, "admin_level": 0, "pcode": ctx.national_pcode,
            "area_name": ctx.country.name, "source_id": "unpd_wpp", "geo_match": "national",
            "source_release": "World Population Prospects 2024 (UN DESA data portal)", "note": ""}
    rows = []

    def add(metric, value, year, bd="", status=None, method="UN WPP 2024, median variant", unit=None, domain="population"):
        y = int(year)
        rows.append({**base, "domain": domain, "metric": metric, "breakdown": bd, "value": float(value),
                     "unit": unit or UNITS.get(metric, "people"), "period": str(y), "period_start": f"{y}-01-01",
                     "period_end": f"{y}-12-31", "status": status or ("projection" if y > LAST_ESTIMATE_YEAR else "sourced"),
                     "method": method})

    births, imr = {}, {}
    for r in main:
        if r.get("variant") != "Median":
            continue
        metric = MAIN.get(int(r["indicatorId"]))
        y = r["timeLabel"][:4]
        if metric in ("births", "infant_mortality_rate", "under5_mortality_rate") and r.get("sex") != "Both sexes":
            continue
        dom = {"infant_mortality_rate": "mortality", "under5_mortality_rate": "mortality", "total_fertility_rate": "fertility",
               "crude_birth_rate": "fertility", "births": "fertility", "married_women_15_49_share": "family_planning",
               "married_women_15_49": "family_planning"}.get(metric, "population")
        bd = f"degree_of_urbanization={DOU.get(r.get('category'), r.get('category'))}" if metric.endswith("urbanization") else ""
        add(metric, r["value"], y, bd=bd, domain=dom)
        if metric == "births":
            births[y] = float(r["value"])
        if metric == "infant_mortality_rate":
            imr[y] = float(r["value"])
    for y, b in births.items():
        if y in imr:
            add("surviving_infants_est", round(b * (1 - imr[y] / 1000)), y, status="estimate", domain="immunization",
                method="WPP births x (1 - WPP infant mortality rate / 1000)", unit="infants")

    by = defaultdict(lambda: defaultdict(float))  # (year, sex) -> age -> people
    for r in ages:
        if r.get("variant") == "Median":
            by[(r["timeLabel"][:4], r["sex"])][int(r["ageStart"])] += float(r["value"])
    bands = {"population_age_6_13": ("Both sexes", range(6, 14)), "population_age_14_18": ("Both sexes", range(14, 19)),
             "girls_10_19": ("Female", range(10, 20)), "women_15_49_wpp": ("Female", range(15, 50)),
             "population_under1_wpp": ("Both sexes", range(0, 1)), "population_under5_wpp": ("Both sexes", range(0, 5))}
    for (y, sex), a in by.items():
        for metric, (s, rng) in bands.items():
            if sex == s:
                add(metric, round(sum(a.get(i, 0) for i in rng)), y,
                    method=f"UN WPP 2024 single-year ages {rng.start}-{rng.stop - 1}, {sex.lower()}")
        if sex == "Both sexes":
            add("children_6_59m_est", round(0.5 * a.get(0, 0) + sum(a.get(i, 0) for i in range(1, 5))), y, status="estimate",
                method="UN WPP 2024: half of age 0 plus ages 1-4 (assumes births spread evenly over the year)")
    return rows, {"qa": {"rows": len(rows), "births_years": sorted(births)}}
