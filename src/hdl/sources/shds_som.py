"""Somali Health and Demographic Survey 2020 (fieldwork 2018-2019), entered by hand from the published report.

The report has no regional tables: only national figures and breakdowns by residence (urban, rural,
nomadic), age, education and wealth. Values live in config/manual/shds_som_2020.csv with the table,
report page and PDF page for each, so anyone can check them against the PDF.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..context import Context

CSV = Path(__file__).resolve().parents[1] / "config" / "manual" / "shds_som_2020.csv"
REPORT = "https://somalia.unfpa.org/sites/default/files/pub-pdf/FINAL%20SHDS%20Report%202020_V7_0.pdf"


def build(ctx: Context):
    if ctx.country.iso3 != "SOM":
        return [], {"skipped": "SHDS is Somalia only"}
    rows = []
    with open(CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "area_id": ctx.national_id, "iso3": "SOM", "admin_level": 0, "pcode": ctx.national_pcode,
                "area_name": ctx.country.name, "source_id": "shds_som", "domain": r["domain"], "metric": r["metric"],
                "breakdown": r["breakdown"], "value": float(r["value"]), "unit": r["unit"], "period": "2020 SHDS",
                "period_start": "2018-01-01", "period_end": "2019-12-31", "status": "sourced", "geo_match": "national",
                "method": f"entered by hand from SHDS 2020 {r['table']}, report p.{r['report_page']} (PDF p.{r['pdf_page']})",
                "source_release": "SHDS 2020 report (Federal Government of Somalia, UNFPA)",
                "note": "; ".join(x for x in (r["note"], "fieldwork 2018-2019; no regional tables in the report") if x),
            })
    return rows, {"qa": {"rows": len(rows), "report": REPORT}}
