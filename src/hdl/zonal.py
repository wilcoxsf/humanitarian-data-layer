"""Raster sums over admin polygons, with fractional pixel coverage (exactextract).

A pixel cut by a boundary contributes in proportion to the share of its area inside each polygon,
so district sums add up to the national sum instead of double counting or dropping edge pixels.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from exactextract import exact_extract


def raster_total(path: Path) -> float:
    """Sum of all valid pixels in the raster (for QA against the admin0 sum)."""
    total = 0.0
    with rasterio.open(path) as src:
        nodata = src.nodata
        for _, window in src.block_windows(1):
            a = src.read(1, window=window, masked=True).astype("float64")
            if nodata is not None:
                a = np.ma.masked_equal(a, nodata)
            a = np.ma.masked_less(a, 0)
            total += float(a.sum()) if a.count() else 0.0
    return total


def zonal_sum(raster: Path, areas: gpd.GeoDataFrame) -> pd.Series:
    """Fraction-weighted sum of the raster inside each area. Index = area_id."""
    g = areas[["area_id", "geometry"]].copy()
    g["geometry"] = g.geometry.make_valid()
    with rasterio.open(raster) as src:
        if src.crs and g.crs and src.crs.to_string() != g.crs.to_string():
            g = g.to_crs(src.crs)
    out = exact_extract(str(raster), g, ["sum"], include_cols=["area_id"], output="pandas")
    return out.set_index("area_id")["sum"].astype("float64")
