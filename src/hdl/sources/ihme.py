"""IHME subnational vaccine coverage 2025 (DTP1, DTP3, MCV1), from a ONE-TIME SNAPSHOT.

There is no public download URL for these rasters. They come from IHME archives downloaded once and
repackaged on 2026-08-27 (old pipeline's Drive bundle, 34 countries, Haiti not included). Every row is
stamped with as_of (config/sources.yaml) and the source is skipped when the snapshot is not on disk,
which is the case on GitHub runners.

Method per admin area: under-1 weighted mean coverage = sum(coverage x WorldPop under-1) / sum(WorldPop
under-1), with each 1 km WorldPop pixel taking the value of the ~5 km IHME cell that contains its centre.
Pixels with population but no IHME value are left out of both sums; the share of under-1 population that
had an IHME value is reported per area. lower/upper are IHME's uncertainty bounds (interval level not
documented in the archive, so not labelled 95%).
"""

from __future__ import annotations

import numpy as np
import rasterio

from ..context import Context
from ..fetch import read_receipt
from ..zonal import zonal_sum
from .worldpop import agesex_url

SNAPSHOT = "ihme/drive_snapshot/countries/{iso3}/rasters/IHME_{ag}_{iso3}_2025_5km_bbox_mean_lower_upper.tif"
ANTIGENS = {"DTP1": "dtp1", "DTP3": "dtp3", "MCV1": "mcv1"}


def _weighted_rasters(ihme_path, wp_path, out_dir, ag):
    """Write pop*mean, pop*lower, pop*upper and pop-with-ihme rasters on the WorldPop grid."""
    with rasterio.open(wp_path) as wp:
        pop = wp.read(1).astype("float64")
        if wp.nodata is not None:
            pop[pop == wp.nodata] = 0
        pop[~np.isfinite(pop) | (pop < 0)] = 0
        prof = wp.profile.copy()
        rows, cols = np.indices(pop.shape)
        xs, ys = rasterio.transform.xy(wp.transform, rows.ravel(), cols.ravel(), offset="center")
    with rasterio.open(ihme_path) as ih:
        bands = ih.read().astype("float64")
        nod = ih.nodata
        r, c = rasterio.transform.rowcol(ih.transform, np.asarray(xs), np.asarray(ys))
        r, c = np.asarray(r).reshape(pop.shape), np.asarray(c).reshape(pop.shape)
        inside = (r >= 0) & (r < ih.height) & (c >= 0) & (c < ih.width)
        vals = np.full((3,) + pop.shape, np.nan)
        vals[:, inside] = bands[:, r[inside], c[inside]]
    # The nodata sentinel is a huge negative float; coverage is a proportion, so anything outside 0..1 is not data.
    vals[(vals < 0) | (vals > 1)] = np.nan
    _ = nod
    has = np.isfinite(vals[0]) & (pop > 0)
    prof.update(dtype="float64", count=1, nodata=None, compress="deflate")
    out = {}
    for name, arr in (("w_mean", vals[0]), ("w_lower", vals[1]), ("w_upper", vals[2])):
        a = np.where(has, arr * pop, 0.0)
        p = out_dir / f"ihme_{ag}_{name}.tif"
        with rasterio.open(p, "w", **prof) as dst:
            dst.write(a, 1)
        out[name] = p
    for name, arr in (("pop_has", np.where(has, pop, 0.0)), ("pop_all", pop)):
        p = out_dir / f"ihme_{ag}_{name}.tif"
        with rasterio.open(p, "w", **prof) as dst:
            dst.write(arr, 1)
        out[name] = p
    return out


def build(ctx: Context):
    iso3 = ctx.country.iso3
    paths = {ag: ctx.fetcher.raw_dir / SNAPSHOT.format(iso3=iso3, ag=ag) for ag in ANTIGENS}
    if not all(p.exists() for p in paths.values()):
        return [], {"skipped": "IHME one-time snapshot not on disk for this country (not public; Haiti not in the snapshot)"}
    url = agesex_url(iso3, 2025, "t", "00")
    wp = ctx.fetcher.download(url, f"worldpop/{ctx.country.iso}/{url.rsplit('/', 1)[-1]}")
    work = ctx.work_dir / "ihme"
    work.mkdir(parents=True, exist_ok=True)
    rows, qa = [], {}
    for ag, short in ANTIGENS.items():
        rec = read_receipt(paths[ag]) or {}
        r = _weighted_rasters(paths[ag], wp, work, short)
        s = {k: zonal_sum(p, ctx.areas) for k, p in r.items()}
        nat = ctx.national_id
        qa[ag] = {"national_mean": round(float(s["w_mean"][nat] / s["pop_has"][nat]), 4) if s["pop_has"][nat] else None,
                  "under1_share_with_ihme_value": round(float(s["pop_has"][nat] / s["pop_all"][nat]), 4)}
        for aid in s["pop_has"].index:
            ph, pa = float(s["pop_has"][aid]), float(s["pop_all"][aid])
            if ph <= 0:
                continue
            lvl = int(aid.split(".")[1])
            share = ph / pa if pa else 0
            for band, label in (("w_mean", ""), ("w_lower", "lower"), ("w_upper", "upper")):
                rows.append({
                    "area_id": aid, "iso3": iso3, "admin_level": lvl, "pcode": aid.split(".", 2)[2],
                    "area_name": ctx.name(aid), "source_id": "ihme", "domain": "immunization",
                    "metric": f"{short}_coverage_ihme", "breakdown": f"bound={label}" if label else "",
                    "value": round(float(s[band][aid]) / ph * 100, 2), "unit": "percent", "period": "2025",
                    "period_start": "2025-01-01", "period_end": "2025-12-31", "status": "derived",
                    "geo_match": "national" if lvl == 0 else "exact",
                    "method": "IHME 2025 coverage surface, WorldPop under-1 weighted mean over the area",
                    "source_release": f"IHME 2025 surface, snapshot file sha256 {str(rec.get('sha256', ''))[:12]}",
                    "note": f"{share:.0%} of under-1 population had an IHME value" if share < 0.95 else "",
                })
    return rows, {"qa": qa, "files": [read_receipt(p) for p in paths.values()]}
