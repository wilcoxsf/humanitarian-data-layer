"""UN DESA Population Division, Estimates and Projections of Family Planning Indicators 2024 (national, 2015-2030).

Read from the public CSV zip (one download, cached, shared by all countries); no API token needed.
Median variant; married/in-union women and all women. Years after 2024 are the model's projections.
"""

from __future__ import annotations

import zipfile

import pandas as pd

from ..context import Context
from ..fetch import read_receipt

URL = "https://population.un.org/wpp/Data_FamilyPlanningIndicators_2024.zip"
INDICATORS = {  # IndicatorShortName -> (metric, unit)
    "CPModP": ("mcpr", "percent"),
    "UNMP": ("unmet_need_any_method", "percent"),
    "UNMModP": ("unmet_need_modern", "percent"),
    "DEMMod": ("demand_satisfied_modern", "percent"),
    "CPModN": ("modern_method_users", "women"),  # the CSV's Value column is a count of women, not thousands
    "UNMModN": ("unmet_need_modern_women", "women"),  # check: NGA 2026 18.9% x 59.0M women 15-49 = 11.15M vs 11.13M
}
CATEGORIES = {"All women": "all", "Married or in a union women": "married_in_union"}
LAST_ESTIMATE_YEAR = 2024
_cache: dict = {}


def _table(ctx: Context) -> pd.DataFrame:
    path = ctx.fetcher.download(URL, "unpd_fp/Data_FamilyPlanningIndicators_2024.zip")
    if str(path) not in _cache:
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.endswith(".csv"))
            d = pd.read_csv(z.open(name), usecols=["IndicatorShortName", "LocationId", "Time", "Variant", "Category", "Value"])
        d = d[d.Variant.eq("Median") & d.IndicatorShortName.isin(INDICATORS) & d.Time.between(2015, 2030)]
        _cache[str(path)] = (d, read_receipt(path))
    return _cache[str(path)]


def build(ctx: Context):
    d, rec = _table(ctx)
    d = d[d.LocationId == int(ctx.country.m49)]
    cats = sorted(d.Category.unique())
    rows = []
    for r in d.itertuples():
        cat = CATEGORIES.get(r.Category)
        if not cat:
            continue
        metric, unit = INDICATORS[r.IndicatorShortName]
        y = int(r.Time)
        rows.append({
            "area_id": ctx.national_id, "iso3": ctx.country.iso3, "admin_level": 0, "pcode": ctx.national_pcode,
            "area_name": ctx.country.name, "source_id": "unpd_fp", "domain": "family_planning", "metric": metric,
            "breakdown": f"women={cat}", "value": float(r.Value), "unit": unit, "period": str(y),
            "period_start": f"{y}-01-01", "period_end": f"{y}-12-31",
            "status": "projection" if y > LAST_ESTIMATE_YEAR else "sourced", "geo_match": "national",
            "method": "UN DESA FPET model, median", "source_release": "Family Planning Indicators 2024", "note": "",
        })
    return rows, {"files": [rec], "qa": {"rows": len(rows), "categories_in_file": cats}}
