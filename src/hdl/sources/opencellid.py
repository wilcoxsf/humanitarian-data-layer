"""OpenCelliD cell towers (crowdsourced), counted per admin area by radio type.

One country file per mobile country code (MCC), downloaded with OPENCELLID_TOKEN; the token is never written
to receipts. Free accounts have a daily download limit: a refusal stops this source and the build carries on;
cached files are reused on the next run. CC BY-SA 4.0: anything published from this must be share-alike.

A tower with no record is not proof of no coverage: OpenCelliD only knows cells that someone's phone reported.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from ..context import Context
from ..fetch import read_receipt
from ..keys import get

URL = "https://opencellid.org/ocid/downloads?token={token}&type=mcc&file={mcc}.csv.gz"
MCC = {"SOM": [637], "SSD": [659], "YEM": [421], "LBN": [415], "HTI": [372], "NGA": [621]}
COLS = ["radio", "mcc", "net", "area", "cell", "unit", "lon", "lat", "range", "samples", "changeable", "created",
        "updated", "averageSignal"]


def build(ctx: Context):
    iso3 = ctx.country.iso3
    mccs = MCC.get(iso3)
    if not mccs:
        return [], {"skipped": "no MCC configured for this country"}
    token = get("OPENCELLID_TOKEN", "opencellid")
    files, frames = [], []
    for mcc in mccs:
        dest = f"opencellid/{ctx.country.iso}/{mcc}.csv.gz"
        cached = ctx.fetcher.raw_dir / dest
        if not token and not cached.exists():
            return [], {"skipped": "OPENCELLID_TOKEN not set"}
        path = ctx.fetcher.download(URL.format(token=token, mcc=mcc), dest,
                                    receipt_url=URL.format(token="***", mcc=mcc))
        files.append(read_receipt(path))
        head = pd.read_csv(path, nrows=1, header=None)
        df = pd.read_csv(path, header=0 if str(head.iloc[0, 0]).lower() == "radio" else None, low_memory=False)
        if df.columns[0] != "radio":
            df.columns = COLS[: len(df.columns)]
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df = df[df.lon.between(-180, 180) & df.lat.between(-90, 90)]
    pts = gpd.GeoDataFrame(df[["radio", "updated"]], geometry=gpd.points_from_xy(df.lon, df.lat), crs=4326)
    rows = []
    for lvl in ctx.levels():
        polys = ctx.areas[ctx.areas.admin_level == lvl][["area_id", "geometry"]]
        j = gpd.sjoin(pts, polys, predicate="within", how="inner")
        counts = j.groupby(["area_id", "radio"]).size().unstack(fill_value=0)
        for aid, r in counts.iterrows():
            for radio, n in list(r.items()) + [("all", int(r.sum()))]:
                if n == 0 and radio != "all":
                    continue
                rows.append({
                    "area_id": aid, "iso3": iso3, "admin_level": lvl, "pcode": aid.split(".", 2)[2],
                    "area_name": ctx.name(aid), "source_id": "opencellid", "domain": "connectivity", "metric": "cell_towers",
                    "breakdown": f"radio={radio}", "value": float(n), "unit": "cells", "period": "latest",
                    "period_start": "", "period_end": files[-1]["retrieved_at"][:10], "status": "derived",
                    "geo_match": "national" if lvl == 0 else "exact",
                    "method": "count of OpenCelliD cells with coordinates inside the area",
                    "source_release": f"OpenCelliD MCC {','.join(map(str, mccs))}",
                    "note": "crowdsourced: no record is not proof of no coverage",
                })
    return rows, {"files": files, "qa": {"cells": len(df), "by_radio": df.radio.value_counts().to_dict()}}
