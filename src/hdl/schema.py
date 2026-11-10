"""The one flat table every source writes into.

One row = one value for one area, metric, breakdown and period, from one source.
Missing is never written as zero: a source that has no value for an area writes no row
(or an explicit row with status "missing" when the absence itself matters).
"""

from __future__ import annotations

import pandas as pd

COLUMNS = [
    "area_id",        # ISO3.level.pcode from the pinned geography; blank if the source area did not match
    "iso3",
    "admin_level",    # 0 national, 1, 2, 3
    "pcode",          # the source's own area code (or label when it has no code)
    "area_name",
    "source_id",      # key in config/sources.yaml
    "domain",         # population, need, food_security, presence, displacement, funding, conflict, risk, immunization, family_planning, nutrition, wealth
    "metric",
    "breakdown",      # key=value pairs joined with ';' (sector, phase, sex, age, series...), '' for none
    "value",
    "value_text",     # optional text value (e.g. a plan status like 'Not set'); value is then empty
    "unit",
    "period",         # human-readable period label: 2026, 2025-07..2025-12, 2024 DHS
    "period_start",
    "period_end",
    "status",         # see STATUSES
    "geo_match",      # exact, name, national, unmatched
    "method",         # how HDL produced the value from the source
    "source_release", # source vintage or file date
    "as_of",          # set only for snapshot sources (one-time download / shared folder): the snapshot date
    "classification", # public (redistributable), restricted (third-party terms not cleared), irc_internal
    "note",
]

KEY = ["iso3", "admin_level", "pcode", "source_id", "metric", "breakdown", "period"]

STATUSES = {
    "sourced": "value as published by the source at this grain",
    "derived": "computed by HDL from source values (sum, aggregation, raster zonal statistic)",
    "projection": "the source's own forward projection (e.g. WorldPop 2026-2030, UN DESA estimates for future years)",
    "stale": "sourced or derived, but the underlying observation is older than the staleness threshold for its domain",
    "partial": "derived from incomplete coverage (e.g. district figures that do not add up to the national figure)",
    "estimate": "HDL cross-source estimate resting on a stated assumption (see method)",
    "missing": "explicitly absent; recorded because the absence matters",
}

DOMAINS = {
    "population", "need", "food_security", "presence", "displacement", "funding", "conflict", "risk",
    "immunization", "family_planning", "nutrition", "wealth", "health", "fertility", "mortality", "education", "connectivity",
}


def breakdown(**kw) -> str:
    """Stable key=value;key=value string, skipping empty values."""
    parts = [f"{k}={v}" for k, v in kw.items() if v not in (None, "", float("nan"))]
    return ";".join(parts)


def frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df = df[COLUMNS]
    df["admin_level"] = pd.to_numeric(df["admin_level"], errors="coerce").astype("Int64")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    for c in COLUMNS:
        if c not in ("admin_level", "value"):
            df[c] = df[c].fillna("").astype(str)
    return df


def validate(df: pd.DataFrame) -> list[str]:
    """Hard errors only. Returns a list of problems (empty = fine)."""
    problems = []
    missing_cols = [c for c in COLUMNS if c not in df.columns]
    if missing_cols:
        return [f"missing columns: {missing_cols}"]
    bad_status = sorted(set(df["status"]) - set(STATUSES))
    if bad_status:
        problems.append(f"unknown status values: {bad_status}")
    bad_domain = sorted(set(df["domain"]) - DOMAINS)
    if bad_domain:
        problems.append(f"unknown domains: {bad_domain}")
    no_value = df[(df["status"] != "missing") & df["value"].isna() & (df["value_text"] == "")]
    if len(no_value):
        problems.append(f"{len(no_value)} non-missing rows have no numeric or text value")
    dup = df.duplicated(KEY, keep=False)
    if dup.any():
        sample = df.loc[dup, KEY].head(5).to_dict("records")
        problems.append(f"{int(dup.sum())} rows share a key, e.g. {sample}")
    return problems
