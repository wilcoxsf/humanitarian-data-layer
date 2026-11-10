"""UN DESA Population Division family-planning estimates (FPET), national, 2015-2030.

The data endpoints need a bearer token (the indicator catalogue is open; data returned 401 on
2026-11-10). Set UNPD_API_TOKEN in the environment (GitHub Actions secret) to enable this source;
without it the source is skipped and the build says so. Not yet run against live data.
"""

from __future__ import annotations

import os

from ..context import Context

API = "https://population.un.org/dataportalapi/api/v1"
INDICATORS = {2: ("mcpr", "percent"), 5: ("unmet_need_modern", "percent"), 8: ("demand_satisfied_modern", "percent"),
              10: ("modern_method_users", "women"), 12: ("unmet_need_modern_women", "women")}
LAST_OBSERVED_GUIDE = 2025


def build(ctx: Context):
    token = os.environ.get("UNPD_API_TOKEN", "").strip()
    if not token:
        return [], {"skipped": "UNPD_API_TOKEN not set (UN DESA data endpoints require a token)"}
    headers = {"Authorization": f"Bearer {token}"}
    ids = ",".join(str(i) for i in INDICATORS)
    url = f"{API}/data/indicators/{ids}/locations/{ctx.country.m49}/start/2015/end/2030?pageSize=1000&format=json"
    rows, page, pages = [], 1, 0
    while url and pages < 20:
        d = ctx.fetcher.get_json(url, f"unpd_fp/{ctx.country.iso}/data_p{page}.json", headers=headers)
        pages += 1
        for r in d.get("data", []):
            if str(r.get("variant", "")).lower() != "median":
                continue
            metric, unit = INDICATORS.get(int(r["indicatorId"]), (None, None))
            if not metric:
                continue
            y = str(r.get("timeLabel", ""))[:4]
            rows.append({
                "area_id": ctx.national_id, "iso3": ctx.country.iso3, "admin_level": 0, "pcode": ctx.national_pcode,
                "area_name": ctx.country.name, "source_id": "unpd_fp", "domain": "family_planning", "metric": metric,
                "breakdown": f"women={r.get('category', '')}", "value": float(r["value"]), "unit": unit, "period": y,
                "period_start": f"{y}-01-01", "period_end": f"{y}-12-31",
                "status": "projection" if int(y) > LAST_OBSERVED_GUIDE else "sourced", "geo_match": "national",
                "method": "UN DESA FPET model estimate (median)", "source_release": "World Family Planning (UN DESA)",
                "note": "",
            })
        url, page = d.get("nextPage"), page + 1
    return rows, {"qa": {"pages": pages, "rows": len(rows)}}
