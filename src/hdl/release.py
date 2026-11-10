"""Write a release: the flat table (CSV + Parquet), areas, boundaries, per-country packs,
a manifest with checksums and receipts, and a human-readable QA report.

Two bundles:
  full/    every source (for local and internal use)
  public/  only sources with `publish: true` in src/hdl/config/sources.yaml (what goes on GitHub Releases)
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import pandas as pd

from . import __version__
from .fetch import sha256_file
from .schema import COLUMNS, KEY


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parent, timeout=10).stdout.strip()
    except Exception:
        return ""


def _write_bundle(dirpath: Path, long: pd.DataFrame, areas: pd.DataFrame, gdfs: dict, presence: pd.DataFrame,
                  boundaries: bool, details: dict | None = None) -> dict:
    dirpath.mkdir(parents=True, exist_ok=True)
    files = {}
    long = long.sort_values(KEY, na_position="first").reset_index(drop=True)
    p = dirpath / "hdl_long.csv.gz"
    long.to_csv(p, index=False, compression={"method": "gzip", "mtime": 0})
    files[p.name] = p
    p = dirpath / "hdl_long.parquet"
    long.to_parquet(p, index=False)
    files[p.name] = p
    p = dirpath / "areas.csv"
    areas.to_csv(p, index=False)
    files[p.name] = p
    if len(presence):
        p = dirpath / "operational_presence.csv.gz"
        presence.to_csv(p, index=False, compression={"method": "gzip", "mtime": 0})
        files[p.name] = p
    for tname, df in (details or {}).items():
        if len(df):
            p = dirpath / f"{tname}.csv.gz"
            df.to_csv(p, index=False, compression={"method": "gzip", "mtime": 0})
            files[p.name] = p
    cdir = dirpath / "countries"
    cdir.mkdir(exist_ok=True)
    for iso3, g in long.groupby("iso3"):
        p = cdir / f"{iso3}.csv"
        g.to_csv(p, index=False)
        files[f"countries/{p.name}"] = p
    if boundaries:
        bdir = dirpath / "boundaries"
        bdir.mkdir(exist_ok=True)
        for iso3, gdf in gdfs.items():
            p = bdir / f"{iso3}_admin.gpkg"
            if p.exists():
                p.unlink()
            for lvl, g in gdf.groupby("admin_level"):
                g.to_file(p, layer=f"admin{lvl}", driver="GPKG")
            files[f"boundaries/{p.name}"] = p
    return {name: {"bytes": f.stat().st_size, "sha256": sha256_file(f)} for name, f in files.items()}


def licenses_md(sources: dict) -> str:
    lines = ["# Data licenses", "",
             "Code in this repository is MIT licensed. Data keeps the license of its source.",
             "Only sources marked publish: yes are included in public release bundles.", "",
             "| Source | Provider | License | Attribution | Publish |", "|---|---|---|---|---|"]
    for sid, s in sources.items():
        lines.append(f"| `{sid}` | {s.get('provider', '')} | {s.get('license', '')} | {s.get('attribution', '')} | "
                     f"{'yes' if s.get('publish') else 'no (terms not yet checked)'} |")
    return "\n".join(lines) + "\n"


def qa_md(manifest: dict) -> str:
    out = [f"# QA report, release {manifest['release_id']}", "",
           f"Built {manifest['built_at']} from commit `{manifest['git_commit'] or 'uncommitted'}`. "
           f"{manifest['rows']['total']:,} rows, {manifest['requests']['total']} upstream requests.", ""]
    if manifest["problems"]:
        out += ["## Problems (blocking)", ""] + [f"- {p}" for p in manifest["problems"]] + [""]
    out += ["## Rows by source and status", "", "| source | status | rows |", "|---|---|---|"]
    for k, v in sorted(manifest["rows"]["by_source_status"].items()):
        s, st = k.split("|")
        out.append(f"| {s} | {st} | {v:,} |")
    out += ["", "## Per country", ""]
    for iso3, c in manifest["countries"].items():
        out.append(f"### {iso3}")
        geo = c.get("geography", {}).get("qa", {})
        out.append(f"- geography: areas {geo.get('areas_by_level')}; errors {geo.get('errors') or 'none'}; "
                   f"warnings {geo.get('warnings') or 'none'}")
        for sid, info in c.items():
            if sid == "geography":
                continue
            if "error" in info:
                out.append(f"- {sid}: ERROR {info['error']}")
            elif "skipped" in info:
                out.append(f"- {sid}: skipped ({info['skipped']})")
            else:
                qa = json.dumps(info.get("qa", {}), default=str)
                out.append(f"- {sid}: {info.get('requests', 0)} requests; qa {qa[:900]}")
        out.append("")
    return "\n".join(out) + "\n"


def write(results: list[dict], long: pd.DataFrame, out_dir: Path, sources: dict, *, release_id: str,
          problems: list[str], requests: dict, log_lines: list[str]) -> dict:
    ok = [r for r in results if "areas" in r]
    areas = pd.concat([r["areas"] for r in ok], ignore_index=True) if ok else pd.DataFrame()
    gdfs = {r["iso3"]: r["gdf"] for r in ok}
    presence = pd.DataFrame([row for r in ok for row in r.get("presence_detail", [])])
    long = long[COLUMNS]

    public_ids = {sid for sid, s in sources.items() if s.get("publish")}
    det: dict[tuple, list] = {}
    for r in ok:
        for k, rows in r.get("details", {}).items():
            det.setdefault(k, []).extend(rows)
    details_full = {t: pd.DataFrame(rows) for (_s, t), rows in det.items()}
    details_pub = {t: pd.DataFrame(rows) for (s, t), rows in det.items() if s in public_ids}
    bundles = {"full": _write_bundle(out_dir / "full", long, areas, gdfs, presence, boundaries=True, details=details_full)}
    pub = long[long.source_id.isin(public_ids) & long.classification.isin(["public", ""])]
    leaked = pub[pub.classification.isin(["restricted", "irc_internal"])]
    if len(leaked):  # belt and braces: never possible through the filter above, checked anyway
        raise RuntimeError(f"refusing to write a public bundle containing {len(leaked)} non-public rows")
    pub_presence = presence if "hapi" in public_ids else presence.iloc[0:0]
    bundles["public"] = _write_bundle(out_dir / "public", pub, areas, gdfs, pub_presence,
                                      boundaries="geography" in public_ids, details=details_pub)

    manifest = {
        "release_id": release_id,
        "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "hdl_version": __version__,
        "git_commit": _git_commit(),
        "countries": {r["iso3"]: r.get("info", {"error": r.get("error")}) for r in results},
        "sources": sources,
        "public_sources": sorted(public_ids),
        "rows": {
            "total": int(len(long)),
            "public": int(len(pub)),
            "by_source_status": {f"{s}|{st}": int(n) for (s, st), n in long.groupby(["source_id", "status"]).size().items()},
            "by_country": {k: int(v) for k, v in long.groupby("iso3").size().items()},
        },
        "requests": requests,
        "problems": problems,
        "files": bundles,
    }
    for d in ("full", "public"):
        (out_dir / d / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
        (out_dir / d / "DATA_LICENSES.md").write_text(licenses_md(sources), encoding="utf-8")
        (out_dir / d / "QA.md").write_text(qa_md(manifest), encoding="utf-8")
    return manifest
