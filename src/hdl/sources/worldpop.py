"""WorldPop Global2 R2025A, 1 km constrained: total population and age/sex denominators.

Metrics (all summed over each admin area with fractional pixel coverage):
  population_total      total population
  population_under1     age 0 (WorldPop age band 00)
  population_under5     ages 0-4 (bands 00 + 01)
  women_15_49           females 15-49 (bands f_15 ... f_45)
Years after 2025 are WorldPop's own forward projections and carry status "projection".
"""

from __future__ import annotations

from ..context import Context
from ..fetch import read_receipt
from ..zonal import raster_total, zonal_sum

BASE = "https://data.worldpop.org/GIS"
RELEASE = "R2025A"
LAST_HISTORICAL = 2025
METHOD = "sum of WorldPop Global2 R2025A 1 km constrained raster over the area, fractional pixel coverage (exactextract)"


def total_url(iso3: str, year: int) -> str:
    return (f"{BASE}/Population/Global_2015_2030/{RELEASE}/{year}/{iso3}/v1/1km_ua/constrained/"
            f"{iso3.lower()}_pop_{year}_CN_1km_{RELEASE}_UA_v1.tif")


def agesex_url(iso3: str, year: int, sex: str, age: str) -> str:
    return (f"{BASE}/AgeSex_structures/Global_2015_2030/{RELEASE}/{year}/{iso3}/v1/1km_ua/constrained/"
            f"{iso3.lower()}_{sex}_{age}_{year}_CN_1km_{RELEASE}_UA_v1.tif")


COMPOSITES = {
    "population_under1": [("t", "00")],
    "population_under5": [("t", "00"), ("t", "01")],
    "women_15_49": [("f", a) for a in ("15", "20", "25", "30", "35", "40", "45")],
}


def build(ctx: Context):
    iso3 = ctx.country.iso3
    s = ctx.settings.get("worldpop", {})
    total_years = s.get("total_years", list(range(2025, 2031)))
    agesex_years = s.get("agesex_years", [2025, 2026])
    rows, qa, files = [], {}, []

    def emit(metric, year, sums, url_note):
        status = "projection" if year > LAST_HISTORICAL else "derived"
        for aid, v in sums.items():
            lvl = int(aid.split(".")[1])
            rows.append({
                "area_id": aid, "iso3": iso3, "admin_level": lvl, "pcode": aid.split(".", 2)[2],
                "area_name": ctx.name(aid), "source_id": "worldpop", "domain": "population",
                "metric": metric, "breakdown": "", "value": round(float(v), 1), "unit": "people",
                "period": str(year), "period_start": f"{year}-01-01", "period_end": f"{year}-12-31",
                "status": status, "geo_match": "national" if lvl == 0 else "exact", "method": METHOD,
                "source_release": f"WorldPop Global2 {RELEASE} v1", "note": url_note,
            })

    for year in total_years:
        url = total_url(iso3, year)
        path = ctx.fetcher.download(url, f"worldpop/{ctx.country.iso}/{url.rsplit('/', 1)[-1]}")
        files.append(read_receipt(path))
        sums = zonal_sum(path, ctx.areas)
        tot = raster_total(path)
        nat = float(sums[ctx.national_id])
        qa[f"population_total {year}"] = {
            "raster_total": round(tot), "admin0_sum": round(nat),
            "admin0_vs_raster": round(nat / tot, 4) if tot else None,
            **{f"admin{lvl}_vs_admin0": round(float(sums[[a for a in sums.index if a.split('.')[1] == str(lvl)]].sum()) / nat, 4)
               for lvl in ctx.levels() if lvl > 0},
        }
        emit("population_total", year, sums, "WorldPop projection" if year > LAST_HISTORICAL else "")

    for year in agesex_years:
        cache = {}
        for metric, parts in COMPOSITES.items():
            acc = None
            for sex, age in parts:
                if (sex, age) not in cache:
                    url = agesex_url(iso3, year, sex, age)
                    path = ctx.fetcher.download(url, f"worldpop/{ctx.country.iso}/{url.rsplit('/', 1)[-1]}")
                    files.append(read_receipt(path))
                    cache[(sex, age)] = zonal_sum(path, ctx.areas)
                acc = cache[(sex, age)] if acc is None else acc + cache[(sex, age)]
            emit(metric, year, acc, f"WorldPop age/sex bands {', '.join(s + '_' + a for s, a in parts)}")

    return rows, {"files": files, "qa": qa}
