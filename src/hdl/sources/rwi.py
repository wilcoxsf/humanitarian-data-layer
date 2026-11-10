"""Meta Relative Wealth Index (about 2.4 km tiles), aggregated to admin areas.

Per area: the mean RWI of tiles whose centre falls inside it, the WorldPop-weighted mean (weights are
WorldPop 2025 people at each tile centre, when the WorldPop raster is cached), and the tile count.
RWI is relative within a country: compare areas inside one country, never across countries.
License CC BY-NC 4.0 (non-commercial).
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio

from ..context import Context
from ..fetch import read_receipt
from .worldpop import total_url

CKAN = "https://data.humdata.org/api/3/action/package_show?id=relative-wealth-index"


def _resource(pkg, iso3: str, country: str):
    iso = iso3.lower()
    for r in pkg["resources"]:
        u = r["url"].lower()
        if u.endswith(f"/{iso}_relative_wealth_index.csv") or r["name"].lower() == f"{country.lower()}_relative_wealth_index.csv":
            return r
    return None


def build(ctx: Context):
    pkg = ctx.fetcher.get_json(CKAN, "rwi/package.json")["result"]
    r = _resource(pkg, ctx.country.iso3, ctx.country.name)
    if r is None:
        return [], {"skipped": f"no Relative Wealth Index file for {ctx.country.name} on HDX"}
    path = ctx.fetcher.download(r["url"], f"rwi/{ctx.country.iso}_relative_wealth_index.csv")
    df = pd.read_csv(path)
    pts = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude), crs=4326)

    wp = ctx.fetcher.raw_dir / "worldpop" / ctx.country.iso / total_url(ctx.country.iso3, 2025).rsplit("/", 1)[-1]
    weighted = Path(wp).exists()
    if weighted:
        with rasterio.open(wp) as src:
            vals = np.array([v[0] for v in src.sample(zip(df.longitude, df.latitude, strict=True))], dtype="float64")
            if src.nodata is not None:
                vals[vals == src.nodata] = np.nan
        pts["w"] = np.where(np.isnan(vals) | (vals < 0), 0.0, vals)

    rows = []
    for lvl in [x for x in ctx.levels()]:
        polys = ctx.areas[ctx.areas.admin_level == lvl][["area_id", "geometry"]]
        j = gpd.sjoin(pts, polys, predicate="within", how="inner")
        for aid, g in j.groupby("area_id"):
            out = {"rwi_mean": float(g.rwi.mean()), "rwi_tiles": float(len(g))}
            if weighted and g.w.sum() > 0:
                out["rwi_mean_popweighted"] = float(np.average(g.rwi, weights=g.w))
            for metric, v in out.items():
                rows.append({
                    "area_id": aid, "iso3": ctx.country.iso3, "admin_level": lvl, "pcode": aid.split(".", 2)[2],
                    "area_name": ctx.name(aid), "source_id": "rwi", "domain": "wealth", "metric": metric, "breakdown": "",
                    "value": round(v, 4), "unit": "tiles" if metric == "rwi_tiles" else "index (relative within country)",
                    "period": "2021", "period_start": "2021-01-01", "period_end": "2021-12-31", "status": "derived",
                    "geo_match": "national" if lvl == 0 else "exact",
                    "method": "mean of Meta RWI tiles with centres in the area" + (", weighted by WorldPop 2025" if metric.endswith("popweighted") else ""),
                    "source_release": "Meta RWI, April 2021", "note": "relative within country only",
                })
    return rows, {"files": [read_receipt(path)], "qa": {"tiles": len(df), "worldpop_weighted": weighted}}
