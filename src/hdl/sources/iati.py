"""IATI Datastore: who reports aid activities in the country, and IRC's own published activities. National.

Two queries per country (key IATI_API_KEY, header Ocp-Apim-Subscription-Key):
  1. all publishers, activities in implementation (status 2): count, and counts by DAC sector group
  2. IRC's activities (IRC Inc., IRC-UK, IRC Sweden as reporting or participating organization): count by status,
     plus a detail table (identifier, title, dates, sectors, budget) for the pack

Counts are of activities, not money: IATI budgets mix currencies, years and double counting through funders
and implementers, so no dollar totals are summed here.
"""

from __future__ import annotations

import json
import urllib.parse
from collections import Counter

from ..context import Context
from ..fetch import read_receipt
from ..keys import get
from ..schema import breakdown

API = "https://api.iatistandard.org/datastore/activity/select"
IRC_REFS = ["US-EIN-13-5660870", "GB-CHC-1065972", "SE-ON-802481-2953"]
SECTOR_GROUPS = {  # DAC 5-digit prefix -> group (first match wins; order matters)
    "12240": "nutrition", "13020": "reproductive_health_family_planning", "13030": "reproductive_health_family_planning",
    "130": "population_reproductive_health", "121": "health", "122": "health", "123": "health",
    "111": "education", "112": "education", "113": "education", "114": "education",
    "720": "emergency_response", "730": "reconstruction_relief", "740": "disaster_prevention",
    "520": "food_assistance", "311": "agriculture", "140": "water_sanitation", "151": "governance_civil_society",
    "160": "social_protection_other_social",
}
STATUS = {"1": "pipeline", "2": "implementation", "3": "finalisation", "4": "closed", "5": "cancelled", "6": "suspended"}


def _group(code: str) -> str:
    for prefix, g in SECTOR_GROUPS.items():
        if str(code).startswith(prefix):
            return g
    return "other"


def build(ctx: Context):
    key = get("IATI_API_KEY", "iati")
    if not key:
        return [], {"skipped": "IATI_API_KEY not set"}
    h = {"Ocp-Apim-Subscription-Key": key}
    iso2, iso = ctx.country.iso2, ctx.country.iso
    q_all = {"q": f"recipient_country_code:{iso2} AND activity_status_code:2", "rows": "0", "wt": "json", "facet": "true",
             "facet.field": ["sector_code", "reporting_org_ref"], "facet.limit": "400", "facet.mincount": "1"}
    url = API + "?" + urllib.parse.urlencode(q_all, doseq=True)
    p1 = ctx.fetcher.download(url, f"iati/{iso}/active_facets.json", headers=h)
    d1 = json.loads(p1.read_text(encoding="utf-8"))
    total = d1["response"]["numFound"]
    facets = d1["facet_counts"]["facet_fields"]
    sec = dict(zip(facets["sector_code"][::2], facets["sector_code"][1::2], strict=False))
    groups = Counter()
    for code, n in sec.items():
        if code.isdigit() and len(code) == 5:
            groups[_group(code)] += n
    pubs = dict(zip(facets["reporting_org_ref"][::2], facets["reporting_org_ref"][1::2], strict=False))

    refs = " OR ".join(f'"{r}"' for r in IRC_REFS)
    q_irc = {"q": f"recipient_country_code:{iso2} AND (reporting_org_ref:({refs}) OR participating_org_ref:({refs}))",
             "rows": "1000", "wt": "json",
             "fl": "iati_identifier,title_narrative,activity_status_code,activity_date_iso_date,activity_date_type,"
                   "sector_code,sector_vocabulary,budget_value,budget_value_currency,reporting_org_ref,last_updated_datetime"}
    p2 = ctx.fetcher.download(API + "?" + urllib.parse.urlencode(q_irc), f"iati/{iso}/irc_activities.json", headers=h)
    docs = json.loads(p2.read_text(encoding="utf-8"))["response"]["docs"]

    base = {"area_id": ctx.national_id, "iso3": ctx.country.iso3, "admin_level": 0, "pcode": ctx.national_pcode,
            "area_name": ctx.country.name, "source_id": "iati", "domain": "funding", "unit": "activities",
            "geo_match": "national", "source_release": "IATI Datastore", "note": ""}
    today = read_receipt(p1)["retrieved_at"][:10]
    rows = [{**base, "metric": "iati_active_activities", "breakdown": "", "value": float(total), "period": today,
             "period_start": today, "period_end": today, "status": "sourced",
             "method": "IATI activities in implementation (status 2) with this recipient country, all publishers"}]
    for g, n in sorted(groups.items()):
        rows.append({**base, "metric": "iati_active_activities", "breakdown": breakdown(sector_group=g), "value": float(n),
                     "period": today, "period_start": today, "period_end": today, "status": "derived",
                     "method": "activities tagged with a DAC sector in the group (an activity can carry several sectors)"})
    status_counts = Counter(STATUS.get(str(d.get("activity_status_code")), "unknown") for d in docs)
    for st, n in sorted(status_counts.items()):
        rows.append({**base, "metric": "iati_irc_activities", "breakdown": breakdown(status=st), "value": float(n),
                     "period": today, "period_start": today, "period_end": today, "status": "sourced",
                     "method": "IATI activities with IRC (Inc., UK or Sweden) as reporting or participating organization"})
    detail = []
    for d in docs:
        dates = dict(zip(d.get("activity_date_type", []), d.get("activity_date_iso_date", []), strict=False))
        detail.append({"iso3": ctx.country.iso3, "iati_identifier": d.get("iati_identifier", ""),
                       "title": "; ".join(d.get("title_narrative", []))[:300],
                       "status": STATUS.get(str(d.get("activity_status_code")), ""),
                       "start": (dates.get("2") or dates.get("1") or "")[:10], "end": (dates.get("4") or dates.get("3") or "")[:10],
                       "sectors": ",".join(d.get("sector_code", [])),
                       "budget": ";".join(f"{v:.0f} {c}" for v, c in zip(d.get("budget_value", []), d.get("budget_value_currency", []), strict=False)),
                       "reporting_org": d.get("reporting_org_ref", ""), "last_updated": str(d.get("last_updated_datetime", ""))[:10]})
    top = sorted(pubs.items(), key=lambda kv: -kv[1])[:25]
    return rows, {"files": [read_receipt(p1), read_receipt(p2)],
                  "detail_tables": {"iati_irc_activities": detail,
                                    "iati_top_publishers": [{"iso3": ctx.country.iso3, "reporting_org_ref": k, "active_activities": v} for k, v in top]},
                  "qa": {"active_activities": total, "irc_activities": len(docs), "irc_by_status": dict(status_counts)}}
