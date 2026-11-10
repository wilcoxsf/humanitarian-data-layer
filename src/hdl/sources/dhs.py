"""The DHS Program API: national and subnational estimates from the latest standard DHS per country.

Subnational DHS regions are matched to admin1 by name (config/name_aliases.csv first). DHS regions
that are not admin areas (Nigeria's geopolitical zones, Haiti's Aire Metropolitaine) stay unmatched
with their DHS label, never forced onto an admin area. Surveys older than 6 years are marked stale.
"""

from __future__ import annotations

import datetime as dt

from ..context import Context
from ..fetch import read_receipt
from ..names import NameMatcher
from ..schema import breakdown

API = "https://api.dhsprogram.com/rest/dhs"
STALE_YEARS = 6

INDICATORS = {
    "FP_CUSM_W_MOD": ("family_planning", "mcpr_married_women", "percent"),
    "FP_CUSA_W_MOD": ("family_planning", "mcpr_all_women", "percent"),
    "FP_NADM_W_UNT": ("family_planning", "unmet_need_married_women", "percent"),
    "FP_NADA_W_UNT": ("family_planning", "unmet_need_all_women", "percent"),
    "CH_VACC_C_DP1": ("immunization", "dtp1_received_12_23m", "percent"),
    "CH_VACC_C_DP3": ("immunization", "dtp3_received_12_23m", "percent"),
    "CH_VACC_C_MSL": ("immunization", "measles_received_12_23m", "percent"),
    "CH_VACC_C_NON": ("immunization", "no_vaccinations_12_23m", "percent"),
    "CH_VACC_C_BAS": ("immunization", "basic_vaccinations_12_23m", "percent"),
    "CN_NUTS_C_WH2": ("nutrition", "wasting_under5", "percent"),
    "CN_NUTS_C_HA2": ("nutrition", "stunting_under5", "percent"),
    "CN_NUTS_C_WA2": ("nutrition", "underweight_under5", "percent"),
    "CM_ECMR_C_U5M": ("mortality", "under5_mortality", "per 1,000 live births"),
    "RH_DELA_C_SKP": ("health", "skilled_birth_attendance", "percent"),
    "FE_FRTR_W_TFR": ("fertility", "total_fertility_rate", "births per woman"),
}


def latest_survey(ctx: Context) -> dict | None:
    code = ctx.country.dhs_code
    d = ctx.fetcher.get_json(f"{API}/surveys?countryIds={code}&surveyType=DHS&f=json&perpage=200",
                             f"dhs/{ctx.country.iso}/surveys.json")
    surveys = [s for s in d.get("Data", []) if s.get("SurveyType") == "DHS"]
    return max(surveys, key=lambda s: int(s["SurveyYear"])) if surveys else None


def build(ctx: Context):
    iso3 = ctx.country.iso3
    sv = latest_survey(ctx)
    if not sv:
        return [], {"qa": {"survey": None}}
    sid, year = sv["SurveyId"], int(sv["SurveyYear"])
    url = (f"{API}/data?surveyIds={sid}&indicatorIds={','.join(INDICATORS)}&breakdown=subnational"
           f"&f=json&perpage=5000&returnGeometry=false")
    path = ctx.fetcher.download(url, f"dhs/{ctx.country.iso}/data_{sid}_subnational.json")
    import json
    data = json.loads(path.read_text(encoding="utf-8")).get("Data", [])
    stale = dt.date.today().year - year > STALE_YEARS
    status = "stale" if stale else "sourced"
    matcher = NameMatcher(ctx.areas, iso3, "dhs", 1)
    rows, unmatched = [], set()
    for r in data:
        if r.get("IsPreferred") not in (None, 1, "1"):
            continue
        ind = INDICATORS.get(r["IndicatorId"])
        if not ind or r.get("Value") in (None, ""):
            continue
        domain, metric, unit = ind
        label = r["CharacteristicLabel"]
        bd = breakdown(by=r.get("ByVariableLabel"))
        if r["CharacteristicCategory"] == "Total":
            aid, lvl, pc, how, name = ctx.national_id, 0, ctx.national_pcode, "national", ctx.country.name
        else:
            pc, how = matcher.match(label.lstrip("."))
            if pc:
                aid, lvl = ctx.match(1, pc)[0], 1
                name = ctx.name(aid)
                how = "name" if how in ("name", "alias") else how
            else:
                aid, lvl, name = "", None, label.lstrip(".")
                pc = f"DHS:{label.lstrip('.')}"
                unmatched.add(label)
                how = "unmatched"
        rows.append({
            "area_id": aid, "iso3": iso3, "admin_level": lvl, "pcode": pc, "area_name": name, "source_id": "dhs",
            "domain": domain, "metric": metric, "breakdown": bd, "value": float(r["Value"]), "unit": unit,
            "period": f"{year} DHS", "period_start": f"{year}-01-01", "period_end": f"{year}-12-31", "status": status,
            "geo_match": how, "method": f"DHS Program estimate, survey {sid}", "source_release": sid,
            "note": (f"survey is {dt.date.today().year - year} years old; " if stale else "")
            + (f"CI {r.get('CILow')}-{r.get('CIHigh')}; " if r.get("CILow") not in (None, "") else "")
            + (f"n={r.get('DenominatorUnweighted')}" if r.get("DenominatorUnweighted") not in (None, "") else ""),
        })
    return rows, {"files": [read_receipt(path)],
                  "qa": {"survey": sid, "survey_year": year, "stale": stale, "rows": len(rows),
                         "unmatched_regions": sorted(unmatched)}}
