"""GRID3 / WorldPop Nigeria population v3.0 (2025): state and LGA totals, a second Nigeria estimate.

Kept separate from WorldPop Global2 (different model and boundaries). GRID3 LGAs are matched to OCHA
admin2 by name within the matched state; anything that does not match exactly stays unmatched.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd

from ..context import Context
from ..fetch import read_receipt
from ..names import NameMatcher, norm

URL = "https://data.worldpop.org/repo/wopr/NGA/population/v3.0/NGA_population_v3_0_admin.zip"
METHOD = "GRID3/WorldPop Nigeria v3.0 published admin total (scaled), matched by name"


def build(ctx: Context):
    path = ctx.fetcher.download(URL, "grid3_nga/NGA_population_v3_0_admin.zip")
    with zipfile.ZipFile(path) as zf:
        read = lambda name: pd.read_csv(io.BytesIO(zf.read(next(n for n in zf.namelist() if n.endswith(name)))))  # noqa: E731
        states, lgas, nat = read("states_pop_total_scaled.csv"), read("lga_pop_total_scaled.csv"), read("national_pop_total_scaled.csv")
    rows, unmatched = [], {"states": [], "lgas": []}
    base = {"iso3": "NGA", "source_id": "grid3_nga", "domain": "population", "metric": "population_total_grid3",
            "breakdown": "", "unit": "people", "period": "2025", "period_start": "2025-01-01", "period_end": "2025-12-31",
            "status": "sourced", "method": METHOD, "source_release": "GRID3/WorldPop NGA population v3.0", "note": ""}

    def add(level, pc, name, value, how):
        aid = ctx.match(level, pc)[0] if pc and level else (ctx.national_id if level == 0 else "")
        rows.append({**base, "area_id": aid, "admin_level": level if aid else None, "pcode": pc or f"GRID3:{name}",
                     "area_name": ctx.name(aid) if aid else name, "value": float(value), "geo_match": how})

    add(0, ctx.national_pcode, "Nigeria", nat.iloc[0, -1], "national")
    sm = NameMatcher(ctx.areas, "NGA", "grid3_nga", 1)
    state_pc = {}  # keyed by normalized name: the state and LGA files spell some states differently
    for r in states.to_dict("records"):
        pc, how = sm.match(r["statename"])
        state_pc[norm(r["statename"])] = pc
        if not pc:
            unmatched["states"].append(r["statename"])
        add(1 if pc else None, pc, r["statename"], r["population"], "name" if pc else "unmatched")
    lga_matchers: dict[str, NameMatcher] = {}
    for r in lgas.to_dict("records"):
        spc = state_pc.get(norm(r["statename"]))
        if spc and spc not in lga_matchers:
            lga_matchers[spc] = NameMatcher(ctx.areas, "NGA", "grid3_nga", 2, parent_pcode=spc)
        pc, how = lga_matchers[spc].match(r["lganame"]) if spc else (None, "unmatched")
        if not pc:
            unmatched["lgas"].append(f"{r['lganame']} ({r['statename']})")
        add(2 if pc else None, pc, f"{r['lganame']} ({r['statename']})", r["population"], "name" if pc else "unmatched")
    return rows, {"files": [read_receipt(path)],
                  "qa": {"states": len(states), "lgas": len(lgas), "unmatched_states": unmatched["states"],
                         "unmatched_lgas": len(unmatched["lgas"]), "unmatched_lga_sample": unmatched["lgas"][:25]}}
