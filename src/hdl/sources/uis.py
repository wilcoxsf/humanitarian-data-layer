"""UNESCO Institute for Statistics: out-of-school children and rates, national (public API, no key).

One request per country. Primary (1), lower secondary (2), upper secondary (3). Years from 2010;
the latest year older than 6 years is marked stale.
"""

from __future__ import annotations

import datetime as dt

from ..context import Context
from ..fetch import read_receipt

URL = "https://api.uis.unesco.org/api/public/data/indicators?{inds}&geoUnit={iso3}"
INDICATORS = {
    "ROFST.1.CP": ("out_of_school_rate_primary", "percent"),
    "ROFST.2.CP": ("out_of_school_rate_lower_secondary", "percent"),
    "ROFST.3.CP": ("out_of_school_rate_upper_secondary", "percent"),
    "OFST.1.CP": ("out_of_school_children_primary", "children"),
    "OFST.2.CP": ("out_of_school_adolescents_lower_secondary", "children"),
    "OFST.3.CP": ("out_of_school_youth_upper_secondary", "children"),
}
FIRST_YEAR, STALE_YEARS = 2010, 6


def build(ctx: Context):
    iso3 = ctx.country.iso3
    inds = "&".join(f"indicator={i}" for i in INDICATORS)
    path = ctx.fetcher.download(URL.format(inds=inds, iso3=iso3), f"uis/{ctx.country.iso}/out_of_school_{iso3}.json")
    import json

    recs = json.loads(path.read_text(encoding="utf-8")).get("records", [])
    latest = {}
    for r in recs:
        if r.get("value") is not None:
            latest[r["indicatorId"]] = max(latest.get(r["indicatorId"], 0), int(r["year"]))
    now, rows = dt.date.today().year, []
    for r in recs:
        if r.get("value") is None or int(r["year"]) < FIRST_YEAR or r["indicatorId"] not in INDICATORS:
            continue
        metric, unit = INDICATORS[r["indicatorId"]]
        y = int(r["year"])
        stale = y == latest[r["indicatorId"]] and now - y > STALE_YEARS
        rows.append({
            "area_id": ctx.national_id, "iso3": iso3, "admin_level": 0, "pcode": ctx.national_pcode,
            "area_name": ctx.country.name, "source_id": "uis", "domain": "education", "metric": metric, "breakdown": "",
            "value": float(r["value"]), "unit": unit, "period": str(y), "period_start": f"{y}-01-01",
            "period_end": f"{y}-12-31", "status": "stale" if stale else "sourced", "geo_match": "national",
            "method": f"UNESCO UIS {r['indicatorId']}", "source_release": "UIS Data API",
            "note": "; ".join(x for x in (f"qualifier={r.get('qualifier')}" if r.get("qualifier") else "",
                                          f"latest year is {now - y} years old" if stale else "") if x),
        })
    return rows, {"files": [read_receipt(path)], "qa": {"latest_year_by_indicator": latest, "rows": len(rows)}}
