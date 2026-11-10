"""HDX HAPI country packages (public CSVs on HDX; no API key needed).

Themes read: humanitarian needs, IPC acute food insecurity, operational presence (3W), IDPs,
refugees and persons of concern, returnees, funding, conflict events (ACLED-derived), national risk
(INFORM), and baseline population (COD-PS). Food prices and rainfall are not read yet.

Area matching: HAPI rows carry OCHA pcodes (admin1_code, admin2_code), matched exactly to the pinned
COD-AB areas. Rows whose pcode is not in the pinned geography keep their pcode with geo_match=unmatched.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

import pandas as pd

from ..context import Context
from ..fetch import read_receipt
from ..schema import breakdown

CKAN = "https://data.humdata.org/api/3/action/package_show?id=hdx-hapi-{iso}"

THEMES = {
    "Affected People: Humanitarian Needs": "needs",
    "Food Security, Nutrition & Poverty: Food Security": "ipc",
    "Coordination & Context: Operational Presence": "presence",
    "Affected People: Internally-Displaced Persons": "idps",
    "Affected People: Refugees & Persons of Concern": "refugees",
    "Affected People: Returnees": "returnees",
    "Coordination & Context: Funding": "funding",
    "Coordination & Context: Conflict Events": "conflict",
    "Coordination & Context: National Risk": "risk",
    "Geography & Infrastructure: Baseline Population": "baseline_pop",
}

NEEDS_STATUS = {"INN": "people_in_need", "TGT": "people_targeted", "REA": "people_reached", "AFF": "people_affected"}
STALE_YEARS = {"idps": 2}


def read_csv(path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if len(df) and df.columns[0] in df and df.iloc[:, 0].str.startswith("#").any():
        df = df[~df.iloc[:, 0].str.startswith("#")]
    return df.reset_index(drop=True)


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v  # NaN is missing, not a value


def fetch(ctx: Context) -> tuple[dict, dict]:
    iso = ctx.country.iso
    pkg = ctx.fetcher.get_json(CKAN.format(iso=iso), f"hapi/{iso}/package.json")["result"]
    paths, meta = {}, {"package": pkg["name"], "license_id": pkg.get("license_id"),
                       "license_title": pkg.get("license_title"), "resources": {}}
    for r in pkg["resources"]:
        theme = next((t for prefix, t in THEMES.items() if r["name"].startswith(prefix) and "Prices" not in r["name"]), None)
        if not theme:
            continue
        fname = r["url"].rsplit("/", 1)[-1].split("?")[0]
        paths[theme] = ctx.fetcher.download(r["url"], f"hapi/{iso}/{fname}",
                                            meta={"resource": r["name"], "last_modified": r.get("last_modified")})
        meta["resources"][theme] = {"name": r["name"], "last_modified": r.get("last_modified"),
                                    "receipt": read_receipt(paths[theme])}
    return paths, meta


class Rows:
    """Collects rows; sums duplicate keys for additive metrics and records it."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.rows: dict[tuple, dict] = {}
        self.duplicates = defaultdict(int)

    def add(self, *, level, pcode, name, metric, value, domain, unit="people", bd="", start="", end="",
            period=None, status="sourced", method="", release="", note="", additive=True):
        if value is None:
            return
        level = int(level)
        aid, how = self.ctx.match(level, pcode)
        pc = self.ctx.national_pcode if level == 0 else pcode
        period = period or (start[:4] if start[:4] == end[:4] else f"{start[:10]}..{end[:10]}")
        key = (level, pc, metric, bd, period)
        if key in self.rows:
            prev = self.rows[key]
            if prev["value"] == value and not prev.get("_summed"):
                self.duplicates[f"{metric} (identical, dropped)"] += 1
                return
            self.duplicates[f"{metric} (different values)"] += 1
            if additive:
                prev["value"] += value
                prev["_summed"] = True
                prev["note"] = "summed source rows that share this area, metric and period"
            return
        self.rows[key] = {
            "area_id": aid, "iso3": self.ctx.country.iso3, "admin_level": level, "pcode": pc,
            "area_name": self.ctx.name(aid) if aid else name, "source_id": "hapi", "domain": domain,
            "metric": metric, "breakdown": bd, "value": value, "unit": unit, "period": period,
            "period_start": start[:10], "period_end": end[:10], "status": status, "geo_match": how,
            "method": method, "source_release": release, "note": note,
            "_primary": True,
        }

    def out(self) -> list[dict]:
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in self.rows.values()]


def _loc(r) -> tuple[int, str, str]:
    lvl = int(r.get("admin_level") or 0)
    if lvl == 2:
        return 2, r.get("admin2_code", ""), r.get("admin2_name", "")
    if lvl == 1:
        return 1, r.get("admin1_code", ""), r.get("admin1_name", "")
    return 0, r.get("location_code", ""), ""


def _release(meta, theme):
    lm = (meta["resources"].get(theme) or {}).get("last_modified") or ""
    return f"HDX HAPI file updated {lm[:10]}" if lm else "HDX HAPI"


# --------------------------------------------------------------------- themes
def needs(df, R: Rows, meta, qa):
    # Files can carry two figures for one area, sector and year: a blank-category row (the headline)
    # and a 'total' row (the total of the disaggregated tables). They can differ a lot (South Sudan
    # Health 2025: 5.66M headline vs 4.84M total). The headline is the main row; the 'total' row is the
    # fallback where no headline exists, and is kept as its own row (category=total) where they differ.
    df = df[df.category.isin(["", "total"]) & df.population_status.isin(NEEDS_STATUS)]
    df = df.assign(_o=(df.category == "total").astype(int)).sort_values("_o", kind="stable")
    rel = _release(meta, "needs")
    for r in df.to_dict("records"):
        lvl, pc, nm = _loc(r)
        metric, v = NEEDS_STATUS[r["population_status"]], num(r["population"])
        bd = breakdown(sector=r["sector_name"])
        kw = dict(level=lvl, pcode=pc, name=nm, metric=metric, domain="need", start=r["reference_period_start"],
                  end=r["reference_period_end"], release=rel)
        if r["category"] == "total":
            period = r["reference_period_start"][:4] if r["reference_period_start"][:4] == r["reference_period_end"][:4] else None
            key = (lvl, R.ctx.national_pcode if lvl == 0 else pc, metric, bd,
                   period or f"{r['reference_period_start'][:10]}..{r['reference_period_end'][:10]}")
            head = R.rows.get(key)
            if head is not None and head.get("_primary") and v is not None and head["value"]:
                if abs(v - head["value"]) / head["value"] > 0.005:
                    R.add(**kw, value=v, bd=breakdown(sector=r["sector_name"], category="total"),
                          method="OCHA HNO total of disaggregated figures via HAPI",
                          note=f"differs from the headline figure ({head['value']:,.0f})")
                continue
            R.add(**kw, value=v, bd=bd, method="OCHA HNO figure via HAPI (category total)")
        else:
            R.add(**kw, value=v, bd=bd, method="OCHA HNO figure via HAPI")
    # Derived admin1 sums where the source only has admin2, plus a coverage check against national.
    have = defaultdict(float)
    parent_of = dict(zip(R.ctx.areas.area_id, R.ctx.areas.parent_pcode, strict=True))
    for (lvl, _pc, metric, bd, period), row in list(R.rows.items()):
        if row["source_id"] == "hapi" and row["domain"] == "need" and lvl == 2:
            parent = parent_of.get(row["area_id"], "") if row["area_id"] else ""
            if parent:
                have[(parent, metric, bd, period, row["period_start"], row["period_end"])] += row["value"]
    a1_exists = {(pc, m, b, p) for (lvl, pc, m, b, p) in R.rows if lvl == 1}
    nat = {(m, b, p): row["value"] for (lvl, pc, m, b, p), row in R.rows.items() if lvl == 0 and row["domain"] == "need"}
    a2tot = defaultdict(float)
    for (_parent, m, b, p, _s, _e), v in have.items():
        a2tot[(m, b, p)] += v
    coverage = {}
    for k, v in a2tot.items():
        if k in nat and nat[k]:
            coverage[k] = v / nat[k]
    partial = {k for k, c in coverage.items() if c < 0.98}
    for (parent, m, b, p, s, e), v in have.items():
        if (parent, m, b, p) in a1_exists:
            continue
        R.add(level=1, pcode=parent, name="", metric=m, value=v, domain="need", bd=b, start=s, end=e, period=p,
              status="partial" if (m, b, p) in partial else "derived",
              method="sum of admin2 HNO rows", release=_release(meta, "needs"),
              note=f"admin2 rows cover {coverage[(m, b, p)]:.0%} of the national figure" if (m, b, p) in coverage else "")
    qa["needs_admin2_vs_national"] = {f"{m} {b} {p}": round(c, 3) for (m, b, p), c in sorted(coverage.items()) if m == "people_in_need"}


def ipc(df, R: Rows, meta, qa, years_back=3):
    if df.empty:
        return
    latest = df.reference_period_end.max()
    cutoff = str(int(latest[:4]) - years_back) + latest[4:10]
    df = df[df.reference_period_end >= cutoff]
    rel = _release(meta, "ipc")
    # IPC often analyses several units inside one district (urban, rural, IDP settlements). Sum the
    # populations of all units in the same area, type, phase and period; recompute the share from sums.
    sums: dict[tuple, float] = defaultdict(float)
    units: dict[tuple, int] = defaultdict(int)
    names: dict[tuple, str] = {}
    for r in df.to_dict("records"):
        lvl, pc, nm = _loc(r)
        if lvl > 0 and not pc:  # analysis unit with no admin code: keep it, labelled, unmatched
            nm = r.get("provider_admin2_name") or r.get("provider_admin1_name") or "unnamed IPC unit"
            pc = f"IPC:{r.get('provider_admin1_name', '')}/{nm}"
        v = num(r["population_in_phase"])
        if v is None:
            continue
        k = (lvl, pc, r["ipc_type"], r["ipc_phase"], r["reference_period_start"][:10], r["reference_period_end"][:10])
        sums[k] += v
        units[k] += 1
        names[k] = nm
    for k, v in sums.items():
        lvl, pc, typ, phase, s, e = k
        status = "projection" if "projection" in typ else "sourced"
        bd = breakdown(ipc_type=typ, phase=phase)
        how = "sum over IPC analysis units in the area" if units[k] > 1 else "IPC/CH acute food insecurity via HAPI"
        R.add(level=lvl, pcode=pc, name=names[k], metric="population_in_ipc_phase", value=v, domain="food_security",
              bd=bd, start=s, end=e, period=f"{s}..{e}", status="derived" if units[k] > 1 and status == "sourced" else status,
              method=how, release=rel, additive=False, note=f"{units[k]} analysis units" if units[k] > 1 else "")
        total = sums.get((lvl, pc, typ, "all", s, e))
        if total:
            R.add(level=lvl, pcode=pc, name=names[k], metric="share_in_ipc_phase", value=round(v / total, 4),
                  domain="food_security", unit="share", bd=bd, start=s, end=e, period=f"{s}..{e}",
                  status="derived" if status == "sourced" else status,
                  method="population in phase / analysed population, from summed units", release=rel, additive=False)
    qa["ipc_latest_period_end"] = latest[:10]
    qa["ipc_units_without_admin_code"] = len({k[1] for k in sums if str(k[1]).startswith("IPC:")})


def presence(df, R: Rows, meta, qa, detail: list):
    if df.empty:
        return
    latest = df.reference_period_start.max()
    df = df[df.reference_period_start == latest]
    rel = _release(meta, "presence")
    orgs = defaultdict(set)
    for r in df.to_dict("records"):
        lvl, pc, nm = _loc(r)
        org = r.get("org_acronym") or r.get("org_name")
        orgs[(lvl, pc, nm, r["sector_name"])].add(org)
        orgs[(lvl, pc, nm, "All sectors")].add(org)
        aid, how = R.ctx.match(lvl, pc)
        detail.append({"area_id": aid, "iso3": R.ctx.country.iso3, "admin_level": lvl, "pcode": pc, "area_name": nm,
                       "sector": r["sector_name"], "org_acronym": r.get("org_acronym", ""), "org_name": r.get("org_name", ""),
                       "org_type": r.get("org_type_description", ""), "period_start": r["reference_period_start"][:10],
                       "period_end": r["reference_period_end"][:10]})
    end = df.reference_period_end.max()
    for (lvl, pc, nm, sector), s in orgs.items():
        R.add(level=lvl, pcode=pc, name=nm, metric="organizations_reported", value=float(len(s)), domain="presence",
              unit="organizations", bd=breakdown(sector=sector), start=latest, end=end,
              method="distinct organizations in the OCHA 3W/5W via HAPI", release=rel, additive=False)
    qa["presence_period"] = f"{latest[:10]}..{end[:10]}"


def idps(df, R: Rows, meta, qa):
    if df.empty:
        return
    rel = _release(meta, "idps")
    today = dt.date.today().isoformat()
    for (op, at), g in df.groupby(["operation", "assessment_type"]):
        last = g.reference_period_end.max()
        g = g[g.reference_period_end == last]
        stale = (int(today[:4]) - int(last[:4])) > STALE_YEARS["idps"]
        for r in g.to_dict("records"):
            lvl, pc, nm = _loc(r)
            R.add(level=lvl, pcode=pc, name=nm, metric="idps", value=num(r["population"]), domain="displacement",
                  bd=breakdown(operation=op, assessment=at, round=r.get("reporting_round")),
                  start=r["reference_period_start"], end=r["reference_period_end"],
                  period=r["reference_period_end"][:10], status="stale" if stale else "sourced",
                  method="IOM DTM via HAPI, latest round of this series; series are not summed", release=rel,
                  note="older than 2 years" if stale else "")
    qa["idps_series"] = int(df.groupby(["operation", "assessment_type"]).ngroups)


def _poc(df, R: Rows, meta, theme, side, years=3):
    if df.empty:
        return
    iso3 = R.ctx.country.iso3
    df = df[(df[side] == iso3) & (df.gender == "all") & (df.age_range == "all")]
    if df.empty:
        return
    last_year = int(df.reference_period_end.max()[:4])
    df = df[df.reference_period_end.str[:4].astype(int) > last_year - years]
    rel = _release(meta, theme)
    other = "origin_location_code" if side == "asylum_location_code" else "asylum_location_code"
    for (grp, start, end), g in df.groupby(["population_group", "reference_period_start", "reference_period_end"]):
        vals = pd.to_numeric(g.population, errors="coerce")
        R.add(level=0, pcode=iso3, name="", metric="persons_of_concern" if theme == "refugees" else "returnees",
              value=float(vals.sum()), domain="displacement", bd=breakdown(group=grp), start=start, end=end,
              status="derived", method="UNHCR via HAPI, summed over origins", release=rel)
        if theme == "refugees":
            for o, v in zip(g[other], vals, strict=True):
                if v and v > 0:
                    R.add(level=0, pcode=iso3, name="", metric="persons_of_concern", value=float(v), domain="displacement",
                          bd=breakdown(group=grp, origin=o), start=start, end=end, method="UNHCR via HAPI", release=rel)


def funding(df, R: Rows, meta, qa):
    rel = _release(meta, "funding")
    for r in df.to_dict("records"):
        bd = breakdown(appeal=r.get("appeal_code"), appeal_type=r.get("appeal_type"))
        for col, metric, unit in [("requirements_usd", "appeal_requirements", "USD"), ("funding_usd", "appeal_funding", "USD"),
                                  ("funding_pct", "appeal_funded_share", "percent")]:
            R.add(level=0, pcode=R.ctx.country.iso3, name="", metric=metric, value=num(r.get(col)), domain="funding",
                  unit=unit, bd=bd, start=r["reference_period_start"], end=r["reference_period_end"],
                  method="OCHA FTS via HAPI", release=rel, additive=False)


def conflict(df, R: Rows, meta, qa, months=12):
    if df.empty:
        return
    last = df.reference_period_end.max()
    first = (pd.Timestamp(last[:10]) - pd.DateOffset(months=months) + pd.Timedelta(days=1)).date().isoformat()
    w = df[df.reference_period_start >= first].copy()
    w["events"] = pd.to_numeric(w.events, errors="coerce")
    w["fatalities"] = pd.to_numeric(w.fatalities, errors="coerce")
    rel = _release(meta, "conflict")
    period = f"{first}..{last[:10]}"
    parent = R.ctx.areas.set_index("pcode").parent_pcode.to_dict()
    agg = defaultdict(lambda: [0.0, 0.0])
    for r in w.to_dict("records"):
        lvl, pc, nm = _loc(r)
        for et in (r["event_type"], "all"):
            for key in {(lvl, pc, nm), (1, parent.get(pc, ""), "") if lvl == 2 else None, (0, R.ctx.country.iso3, "")} - {None}:
                if key[1] == "":
                    continue
                a = agg[(key, et)]
                a[0] += 0 if pd.isna(r["events"]) else r["events"]
                a[1] += 0 if pd.isna(r["fatalities"]) else r["fatalities"]
    for ((lvl, pc, nm), et), (ev, fa) in agg.items():
        for metric, v in (("conflict_events", ev), ("conflict_fatalities", fa)):
            R.add(level=lvl, pcode=pc, name=nm, metric=metric, value=v, domain="conflict", unit="events" if metric == "conflict_events" else "deaths",
                  bd=breakdown(event_type=et), start=first, end=last, period=period, status="derived",
                  method=f"sum of ACLED monthly admin2 aggregates via HAPI over {months} months", release=rel, additive=False)
    qa["conflict_window"] = period


def risk(df, R: Rows, meta, qa):
    rel = _release(meta, "risk")
    for r in df.to_dict("records"):
        for col in ("overall_risk", "hazard_exposure_risk", "vulnerability_risk", "coping_capacity_risk", "global_rank"):
            R.add(level=0, pcode=R.ctx.country.iso3, name="", metric=f"inform_{col}", value=num(r.get(col)), domain="risk",
                  unit="rank" if col == "global_rank" else "index 0-10", start=r["reference_period_start"],
                  end=r["reference_period_end"], method="INFORM Risk via HAPI", release=rel, additive=False)


def baseline_pop(df, R: Rows, meta, qa):
    if df.empty:
        return
    last = df.reference_period_start.max()
    df = df[df.reference_period_start == last]
    rel = _release(meta, "baseline_pop")
    for r in df.to_dict("records"):
        if r.get("gender") != "all":
            continue
        age = r.get("age_range", "")
        metric = {"all": "population_total_cod_ps", "0-4": "population_under5_cod_ps"}.get(age)
        if not metric:
            continue
        lvl, pc, nm = _loc(r)
        R.add(level=lvl, pcode=pc, name=nm, metric=metric, value=num(r["population"]), domain="population",
              start=r["reference_period_start"], end=r["reference_period_end"],
              method="OCHA COD-PS via HAPI (not WorldPop)", release=rel, additive=False)


def build(ctx: Context):
    paths, meta = fetch(ctx)
    R, qa, detail = Rows(ctx), {}, []
    frames = {t: read_csv(p) for t, p in paths.items()}
    empty = pd.DataFrame()
    needs(frames.get("needs", empty), R, meta, qa) if "needs" in frames else None
    ipc(frames.get("ipc", empty), R, meta, qa) if "ipc" in frames else None
    presence(frames.get("presence", empty), R, meta, qa, detail) if "presence" in frames else None
    idps(frames.get("idps", empty), R, meta, qa) if "idps" in frames else None
    if "refugees" in frames:
        _poc(frames["refugees"], R, meta, "refugees", "asylum_location_code")
    if "returnees" in frames:
        _poc(frames["returnees"], R, meta, "returnees", "origin_location_code")
    funding(frames["funding"], R, meta, qa) if "funding" in frames else None
    conflict(frames["conflict"], R, meta, qa) if "conflict" in frames else None
    risk(frames["risk"], R, meta, qa) if "risk" in frames else None
    baseline_pop(frames["baseline_pop"], R, meta, qa) if "baseline_pop" in frames else None
    rows = R.out()
    qa["themes_found"] = sorted(paths)
    qa["themes_missing"] = sorted(set(THEMES.values()) - set(paths))
    qa["duplicate_keys_by_metric"] = dict(R.duplicates)
    qa["unmatched_rows"] = sum(1 for r in rows if r["geo_match"] == "unmatched")
    return rows, {"meta": meta, "qa": qa, "presence_detail": detail}
