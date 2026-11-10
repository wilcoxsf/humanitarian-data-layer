"""Command line.

    hdl build --countries SOM,NGA --sources all --release 2026.11.1 [--offline] [--refresh]
    hdl sources        list sources and whether they publish
    hdl countries      list active countries
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import build


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hdl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="fetch, standardize, QA and write a release")
    b.add_argument("--countries", default="all", help="comma-separated ISO3 codes, or 'all' active countries")
    b.add_argument("--sources", default="all", help=f"comma-separated: {','.join(build.SOURCES)} or 'all'")
    b.add_argument("--release", default=None, help="release id, default YYYY.MM.DD-dev")
    b.add_argument("--out", default=None, help="output folder, default build/<release>")
    b.add_argument("--offline", action="store_true", help="use cached downloads only; no network")
    b.add_argument("--refresh", action="store_true", help="re-download even if cached")
    b.add_argument("--max-requests", type=int, default=1500, help="hard cap on upstream requests for the run")
    b.add_argument("--reuse", default=None, help="hdl_long.parquet path or release URL: keep its rows for sources not rebuilt now")
    b.add_argument("--plugin", action="append", default=[], help="python package that adds sources (SOURCES, SPECS); repeatable")
    sub.add_parser("sources")
    sub.add_parser("countries")
    a = ap.parse_args(argv)

    if a.cmd == "sources":
        for sid, s in build.load_sources().items():
            print(f"{sid:12s} publish={'yes' if s.get('publish') else 'no ':3s}  {s.get('license', '')}")
        return 0
    if a.cmd == "countries":
        for c in build.load_countries().values():
            print(c.iso3, c.name)
        return 0

    for p in getattr(a, "plugin", []) or []:
        build.load_plugin(p)
    countries = list(build.load_countries()) if a.countries == "all" else [c.strip().upper() for c in a.countries.split(",")]
    sources = list(build.SOURCES) if a.sources == "all" else [s.strip() for s in a.sources.split(",")]
    unknown = [s for s in sources if s not in build.SOURCES]
    if unknown:
        print(f"unknown sources: {unknown}", file=sys.stderr)
        return 2
    release = a.release or f"{dt.date.today():%Y.%m.%d}-dev"
    out = Path(a.out) if a.out else build.ROOT / "build" / release
    m = build.run(countries, sources, out, offline=a.offline, refresh=a.refresh, max_requests=a.max_requests,
                  release_id=release, reuse=a.reuse)
    print(f"wrote {out}")
    return 1 if m["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
