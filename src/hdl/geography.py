"""Admin areas from OCHA COD-AB (via HDX), pinned per build.

area_id = ISO3.level.pcode, e.g. SOM.2.SO1101. The pcode is OCHA's; the level makes the id
unambiguous; the ISO3 prefix keeps ids readable. A new COD-AB vintage that changes a pcode
produces a new area_id, and the old one simply stops appearing in later releases.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .fetch import Fetcher, read_receipt

CKAN = "https://data.humdata.org/api/3/action/package_show?id=cod-ab-{iso}"
EQUAL_AREA = "EPSG:6933"


def area_id(iso3: str, level: int, pcode: str) -> str:
    return f"{iso3}.{int(level)}.{pcode}"


def _pick(cols: list[str], *cands: str) -> str | None:
    low = {c.lower(): c for c in cols}
    for c in cands:
        if c.lower() in low:
            return low[c.lower()]
    return None


def fetch(fetcher: Fetcher, iso3: str) -> tuple[Path, dict]:
    iso = iso3.lower()
    pkg = fetcher.get_json(CKAN.format(iso=iso), f"geography/{iso}/package.json")["result"]
    res = [r for r in pkg["resources"] if (r.get("format") or "").lower() == "geojson"]
    if not res:
        raise RuntimeError(f"{iso3}: no GeoJSON resource in cod-ab-{iso}")
    r = res[0]
    meta = {
        "dataset": pkg["name"],
        "dataset_date": pkg.get("dataset_date"),
        "license_id": pkg.get("license_id"),
        "license_title": pkg.get("license_title"),
        "resource": r["name"],
        "resource_last_modified": r.get("last_modified"),
    }
    path = fetcher.download(r["url"], f"geography/{iso}/{r['url'].rsplit('/', 1)[-1]}", meta=meta)
    return path, meta


def _layers(zip_path: Path, iso: str) -> dict[int, str]:
    """Map admin level -> member name, preferring the non edge-matched layer."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    out: dict[int, str] = {}
    for n in names:
        base = n.rsplit("/", 1)[-1].lower()
        m = re.fullmatch(rf"{iso}_admin(\d)(_em)?\.geojson", base)
        if not m:
            continue
        lvl, em = int(m.group(1)), bool(m.group(2))
        if lvl not in out or (not em and out[lvl].lower().endswith("_em.geojson")):
            out[lvl] = n
    return dict(sorted(out.items()))


def load(zip_path: Path, iso3: str, max_level: int = 3) -> gpd.GeoDataFrame:
    """All admin levels 0..max_level as one GeoDataFrame with HDL area columns."""
    iso = iso3.lower()
    frames, dropped = [], []
    for lvl, member in _layers(zip_path, iso).items():
        if lvl > max_level:
            continue
        g = gpd.read_file(f"zip://{zip_path}!{member}")
        cols = list(g.columns)
        pc = _pick(cols, f"adm{lvl}_pcode")
        nm = _pick(cols, f"adm{lvl}_name", f"adm{lvl}_en", f"adm{lvl}_fr", f"adm{lvl}_ref")
        parent = _pick(cols, f"adm{lvl - 1}_pcode") if lvl > 0 else None
        if pc is None or nm is None:
            raise RuntimeError(f"{iso3} admin{lvl}: cannot find pcode/name columns in {cols}")
        valid_on = _pick(cols, "valid_on", "validon", "date")
        out = gpd.GeoDataFrame({
            "iso3": iso3,
            "admin_level": lvl,
            "pcode": g[pc].astype(str).str.strip(),
            "name": g[nm].astype(str).str.strip(),
            "parent_pcode": g[parent].astype(str).str.strip() if parent else "",
            "valid_on": g[valid_on].astype(str).str[:10] if valid_on else "",
        }, geometry=g.geometry, crs=g.crs)
        bad = out.pcode.str.lower().isin(["", "0", "none", "nan", "null"])
        if bad.any():  # e.g. Lebanon's admin3 'Conflict' polygons: no pcode, so no stable identity
            dropped.append(f"admin{lvl}: {int(bad.sum())} features without a pcode "
                           f"(names: {sorted(out.loc[bad, 'name'].unique())[:5]})")
            out = out[~bad]
        frames.append(out)
    if not frames:
        raise RuntimeError(f"{iso3}: no admin layers found in {zip_path.name}")
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.set_crs(4326, allow_override=gdf.crs is None).to_crs(4326)
    gdf["area_id"] = [area_id(iso3, lvl, pc) for lvl, pc in zip(gdf.admin_level, gdf.pcode, strict=True)]
    gdf["parent_area_id"] = [
        area_id(iso3, lvl - 1, pp) if lvl > 0 and pp else ""
        for lvl, pp in zip(gdf.admin_level, gdf.parent_pcode, strict=True)
    ]
    gdf["area_km2"] = gdf.geometry.to_crs(EQUAL_AREA).area / 1e6
    gdf = gdf[["area_id", "iso3", "admin_level", "pcode", "name", "parent_area_id", "parent_pcode",
               "valid_on", "area_km2", "geometry"]]
    gdf.attrs["dropped"] = dropped
    return gdf


def qa(gdf: gpd.GeoDataFrame) -> dict:
    """Hierarchy and identity checks. Returns counts; 'errors' must be empty to publish."""
    errors, warnings = [], list(gdf.attrs.get("dropped", []))
    dup = gdf[gdf.duplicated("area_id", keep=False)]
    if len(dup):
        errors.append(f"duplicate area_id: {sorted(dup.area_id.unique())[:10]}")
    ids = set(gdf.area_id)
    orphans = gdf[(gdf.admin_level > 0) & ~gdf.parent_area_id.isin(ids)]
    if len(orphans):  # e.g. South Sudan's Abyei (SS0001) sits under a special area with no admin1 polygon
        warnings.append(f"{len(orphans)} areas whose parent is not in the parent layer: "
                        f"{orphans.area_id.head(5).tolist()} (kept; they roll up to admin0 only)")
    invalid = int((~gdf.geometry.is_valid).sum())
    if invalid:
        warnings.append(f"{invalid} invalid geometries (made valid before zonal statistics)")
    if (gdf.admin_level == 0).sum() != 1:
        errors.append(f"expected one admin0 area, found {(gdf.admin_level == 0).sum()}")
    # Children's total area should be close to the parent's (catches truncated layers).
    area_by = gdf.groupby("admin_level").area_km2.sum()
    for lvl in area_by.index:
        if lvl == 0:
            continue
        ratio = area_by[lvl] / area_by[0]
        if abs(ratio - 1) > 0.02:
            warnings.append(f"admin{lvl} total area is {ratio:.3f} x admin0")
    return {
        "areas_by_level": {int(k): int(v) for k, v in gdf.admin_level.value_counts().sort_index().items()},
        "errors": errors,
        "warnings": warnings,
    }


def areas_table(gdf: gpd.GeoDataFrame, receipt_meta: dict | None = None) -> pd.DataFrame:
    df = pd.DataFrame(gdf.drop(columns="geometry"))
    df["source_dataset"] = (receipt_meta or {}).get("dataset", "")
    df["area_km2"] = df["area_km2"].round(2)
    return df


def build(fetcher: Fetcher, iso3: str, max_level: int = 3) -> tuple[gpd.GeoDataFrame, dict]:
    path, meta = fetch(fetcher, iso3)
    gdf = load(path, iso3, max_level=max_level)
    rec = read_receipt(path) or {}
    info = {"receipt": rec, "meta": meta, "qa": qa(gdf)}
    return gdf, info


def dump_info(info: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, indent=1, default=str), encoding="utf-8")
