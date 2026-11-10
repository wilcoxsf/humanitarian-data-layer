"""UNICEF/WHO/World Bank child malnutrition, national, from the UNICEF SDMX data warehouse (one request per country).

Two kinds of numbers, kept apart:
  *_jme_model  JME country-level modelled estimates (stunting, overweight), annual to the latest year
  survey       the latest national survey estimate (wasting, severe wasting, stunting), with its survey name;
               older than 6 years = stale
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from ..context import Context
from ..fetch import read_receipt

URL = ("https://sdmx.data.unicef.org/ws/public/sdmxapi/rest/data/UNICEF,NUTRITION,1.0/"
       "{iso3}.{inds}./?format=csv&startPeriod=2000")
INDICATORS = {
    "NT_ANT_HAZ_NE2_MOD": ("stunting_under5_jme_model", "model"),
    "NT_ANT_WHZ_PO2_MOD": ("overweight_under5_jme_model", "model"),
    "NT_ANT_WHZ_NE2": ("wasting_under5_survey", "survey"),
    "NT_ANT_WHZ_NE3": ("severe_wasting_under5_survey", "survey"),
    "NT_ANT_HAZ_NE2": ("stunting_under5_survey", "survey"),
}
DIMS = ["SEX", "AGE", "WEALTH_QUINTILE", "RESIDENCE", "MATERNAL_EDU_LVL", "HEAD_OF_HOUSE"]
STALE_YEARS = 6


def build(ctx: Context):
    iso3 = ctx.country.iso3
    path = ctx.fetcher.download(URL.format(iso3=iso3, inds="+".join(INDICATORS)),
                                f"unicef_nutrition/{ctx.country.iso}/nutrition_{iso3}.csv")
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in DIMS:
        if c in df:
            df = df[df[c] == "_T"]
    rows, now = [], dt.date.today().year
    for ind, (metric, kind) in INDICATORS.items():
        d = df[(df.INDICATOR == ind) & (df.OBS_VALUE != "")]
        if d.empty:
            continue
        if kind == "survey":
            d = d.sort_values("TIME_PERIOD").tail(1)
        for r in d.to_dict("records"):
            y = r["TIME_PERIOD"][:4]
            stale = kind == "survey" and now - int(y) > STALE_YEARS
            rows.append({
                "area_id": ctx.national_id, "iso3": iso3, "admin_level": 0, "pcode": ctx.national_pcode,
                "area_name": ctx.country.name, "source_id": "unicef_nutrition", "domain": "nutrition", "metric": metric,
                "breakdown": "", "value": float(r["OBS_VALUE"]), "unit": "percent", "period": y,
                "period_start": f"{y}-01-01", "period_end": f"{y}-12-31", "status": "stale" if stale else "sourced",
                "geo_match": "national", "method": "JME modelled estimate" if kind == "model" else "national survey estimate (latest)",
                "source_release": r.get("DATA_SOURCE", "")[:150],
                "note": (f"survey is {now - int(y)} years old; " if stale else "")
                + (f"bounds {r.get('LOWER_BOUND')}-{r.get('UPPER_BOUND')}" if r.get("LOWER_BOUND") else ""),
            })
    return rows, {"files": [read_receipt(path)], "qa": {"rows": len(rows), "metrics": sorted({r["metric"] for r in rows})}}
