"""Cross-source estimates HDL computes after the sources are built. Each rests on a stated assumption,
so every row carries status "estimate" and the assumption in `method`.

zero_dose_children_estimate (national): WorldPop under-1 population x (1 - WUENIC DTP1 coverage).
Assumes the WorldPop under-1 count approximates the surviving-infant cohort WUENIC coverage refers to.
National only: national coverage is never applied to admin areas.
"""

from __future__ import annotations

import pandas as pd


def build(iso3: str, long: pd.DataFrame) -> list[dict]:
    d = long[long.iso3 == iso3]
    u1 = d[(d.source_id == "worldpop") & (d.metric == "population_under1") & (d.admin_level == 0)]
    dtp1 = d[(d.source_id == "wuenic") & (d.metric == "dtp1_coverage")]
    if u1.empty or dtp1.empty:
        return []
    cov = dtp1.loc[dtp1.period.astype(int).idxmax()]
    rows = []
    for r in u1.to_dict("records"):
        if int(r["period"]) < int(cov["period"]):
            continue
        rows.append({**{k: r[k] for k in ("area_id", "iso3", "admin_level", "pcode", "area_name")},
                     "source_id": "derived", "domain": "immunization", "metric": "zero_dose_children_estimate",
                     "breakdown": "", "value": round(r["value"] * (1 - cov["value"] / 100.0)), "unit": "children",
                     "period": r["period"], "period_start": r["period_start"], "period_end": r["period_end"],
                     "status": "estimate", "geo_match": "national",
                     "method": f"WorldPop under-1 ({r['period']}) x (1 - WUENIC DTP1 {cov['period']} of {cov['value']:.0f}%)",
                     "source_release": f"{r['source_release']}; {cov['source_release']}", "note": "assumes under-1 population ~ surviving infants"})
    return rows
