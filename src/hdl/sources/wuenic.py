"""WUENIC national immunization coverage from the UNICEF SDMX data warehouse (one request per country).

National only: WUENIC is never copied down to admin areas.
"""

from __future__ import annotations

import pandas as pd

from ..context import Context
from ..fetch import read_receipt

URL = ("https://sdmx.data.unicef.org/ws/public/sdmxapi/rest/data/UNICEF,IMMUNISATION,1.0/"
       "{iso3}.{inds}./?format=csv&startPeriod={start}")
INDICATORS = {"IM_DTP1": "dtp1_coverage", "IM_DTP3": "dtp3_coverage", "IM_MCV1": "mcv1_coverage",
              "IM_MCV2": "mcv2_coverage", "IM_PCV3": "pcv3_coverage", "IM_POL3": "pol3_coverage"}


def build(ctx: Context):
    iso3 = ctx.country.iso3
    start = ctx.settings.get("wuenic", {}).get("start_year", 2015)
    url = URL.format(iso3=iso3, inds="+".join(INDICATORS), start=start)
    path = ctx.fetcher.download(url, f"wuenic/{ctx.country.iso}/unicef_immunisation_{iso3}.csv")
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    rows = []
    for r in df.to_dict("records"):
        metric = INDICATORS.get(r["INDICATOR"])
        if not metric or r["OBS_VALUE"] == "":
            continue
        y = r["TIME_PERIOD"][:4]
        rows.append({
            "area_id": ctx.national_id, "iso3": iso3, "admin_level": 0, "pcode": ctx.national_pcode,
            "area_name": ctx.country.name, "source_id": "wuenic", "domain": "immunization", "metric": metric,
            "breakdown": "", "value": float(r["OBS_VALUE"]), "unit": "percent", "period": y,
            "period_start": f"{y}-01-01", "period_end": f"{y}-12-31", "status": "sourced", "geo_match": "national",
            "method": "WHO/UNICEF estimate of national coverage (WUENIC)", "source_release": r.get("DATA_SOURCE", ""),
            "note": f"obs_status={r.get('OBS_STATUS', '')}",
        })
    latest = {}
    for r in rows:
        latest[r["metric"]] = max(latest.get(r["metric"], ""), r["period"])
    return rows, {"files": [read_receipt(path)], "qa": {"latest_year_by_indicator": latest}}
