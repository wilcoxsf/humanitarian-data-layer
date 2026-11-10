"""Build orchestration: geography first, then every source, per country."""

from __future__ import annotations

import csv
import importlib
import json
import os
import traceback
from pathlib import Path

import pandas as pd
import yaml

from . import geography, schema
from .context import Context, Country
from .fetch import Fetcher, UpstreamBlocked
from .sources import derived, dhs, grid3_nga, hapi, ihme, rwi, unpd_fp, worldpop, wuenic

CONFIG = Path(__file__).resolve().parent / "config"  # shipped inside the package
ROOT = Path(os.environ.get("HDL_WORKDIR", Path.cwd()))  # where data/ and build/ go (run from the repo root)
RAW = Path(os.environ.get("HDL_RAW_DIR", ROOT / "data" / "raw"))

SOURCES = {
    "worldpop": worldpop.build,
    "ihme": ihme.build,
    "hapi": hapi.build,
    "wuenic": wuenic.build,
    "dhs": dhs.build,
    "unpd_fp": unpd_fp.build,
    "rwi": rwi.build,
    "grid3_nga": grid3_nga.build,
}


def load_countries(path: Path = CONFIG / "countries.csv") -> dict[str, Country]:
    out = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["active"].strip().lower() == "true":
                out[r["iso3"]] = Country(r["iso3"], r["iso2"], r["m49"], r["country"], r.get("dhs_code", ""))
    return out


EXTRA_SPECS: dict = {}  # source specs added by plugins (e.g. a private overlay package)


def load_sources(path: Path = CONFIG / "sources.yaml") -> dict:
    return {**yaml.safe_load(path.read_text(encoding="utf-8")), **EXTRA_SPECS}


def load_plugin(module_name: str) -> list[str]:
    """Import a package that adds sources. It must expose SOURCES {id: build(ctx)} and SPECS {id: spec dict}
    (same fields as config/sources.yaml). Returns the source ids it added."""
    mod = importlib.import_module(module_name)
    clash = set(mod.SOURCES) & set(SOURCES)
    if clash:
        raise ValueError(f"plugin {module_name} redefines sources {sorted(clash)}")
    SOURCES.update(mod.SOURCES)
    EXTRA_SPECS.update(mod.SPECS)
    return list(mod.SOURCES)


def classification(spec: dict) -> str:
    return spec.get("classification") or ("public" if spec.get("publish") else "restricted")


def load_settings(path: Path = CONFIG / "settings.yaml") -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def make_context(iso3: str, *, offline=False, refresh=False, max_requests=400, fetcher: Fetcher | None = None,
                 work_dir: Path | None = None) -> Context:
    country = load_countries()[iso3]
    f = fetcher or Fetcher(RAW, max_requests=max_requests, offline=offline, refresh=refresh)
    gdf, info = geography.build(f, iso3)
    ctx = Context(country, gdf, f, work_dir or ROOT / "build" / "work" / iso3, load_settings())
    ctx.geo_info = info
    return ctx


def build_country(iso3: str, sources: list[str], fetcher: Fetcher, log) -> dict:
    ctx = make_context(iso3, fetcher=fetcher)
    result = {"iso3": iso3, "areas": geography.areas_table(ctx.areas, ctx.geo_info["meta"]), "gdf": ctx.areas,
              "frames": [], "info": {"geography": {k: v for k, v in ctx.geo_info.items()}}, "presence_detail": []}
    if ctx.geo_info["qa"]["errors"]:
        log(f"{iso3}: geography QA errors {ctx.geo_info['qa']['errors']}")
    for name in sources:
        if name == "grid3_nga" and iso3 != "NGA":
            continue
        if name == "dhs" and not ctx.country.dhs_code:
            result["info"][name] = {"skipped": "no DHS Program survey for this country"}
            continue
        start = fetcher.requests
        try:
            rows, info = SOURCES[name](ctx)
        except UpstreamBlocked as e:
            log(f"{iso3} {name}: BLOCKED, stopping this source: {e}")
            result["info"][name] = {"error": f"blocked: {e}"}
            continue
        except Exception as e:  # one broken source must not sink the country
            log(f"{iso3} {name}: FAILED {e.__class__.__name__}: {e}")
            result["info"][name] = {"error": f"{e.__class__.__name__}: {e}", "traceback": traceback.format_exc()[-2000:]}
            continue
        if name == "hapi":
            result["presence_detail"] = info.pop("presence_detail", [])
        info["requests"] = fetcher.requests - start
        result["info"][name] = info
        df = schema.frame(rows)
        spec = load_sources().get(name, {})
        df["classification"] = classification(spec)
        if spec.get("snapshot"):
            df["as_of"] = str(spec.get("as_of", ""))
            info["as_of"] = spec.get("as_of")
        result["frames"].append(df)
        log(f"{iso3} {name}: {len(df):,} rows, {info['requests']} requests")
    return result


def run(countries: list[str], sources: list[str], out_dir: Path, *, offline=False, refresh=False,
        max_requests=1500, release_id="dev", reuse: Path | str | None = None) -> dict:
    from . import release

    out_dir.mkdir(parents=True, exist_ok=True)
    log_lines = []

    def log(msg):
        print(msg, flush=True)
        log_lines.append(msg)

    fetcher = Fetcher(RAW, max_requests=max_requests, offline=offline, refresh=refresh)
    results = []
    for iso3 in countries:
        try:
            results.append(build_country(iso3, sources, fetcher, log))
        except Exception as e:
            log(f"{iso3}: geography FAILED {e.__class__.__name__}: {e}")
            results.append({"iso3": iso3, "error": str(e)})
    frames = [f for r in results for f in r.get("frames", [])]
    if reuse:
        # Carry rows from an earlier build or a published release (path or URL) for sources not rebuilt here.
        if str(reuse).startswith("http"):
            name = "__".join(str(reuse).rstrip("/").split("/")[-2:])
            reuse = fetcher.download(str(reuse), f"releases/{name}")
        old = schema.frame(pd.read_parquet(reuse).to_dict("records"))
        specs = load_sources()
        old["classification"] = [c or classification(specs.get(s, {})) for c, s in zip(old.classification, old.source_id, strict=True)]
        old = old[old.iso3.isin(countries) & ~old.source_id.isin(sources)]
        log(f"reused {len(old):,} rows from {reuse} for sources {sorted(old.source_id.unique())}")
        frames.append(old)
    long = pd.concat(frames, ignore_index=True) if frames else schema.frame([])
    extra = [row for iso3 in countries for row in derived.build(iso3, long)]
    if extra:
        ex = schema.frame(extra)
        ex["classification"] = classification(load_sources().get("derived", {}))
        long = pd.concat([long, ex], ignore_index=True)
        log(f"derived estimates: {len(extra)} rows")
    problems = schema.validate(long)
    manifest = release.write(results, long, out_dir, load_sources(), release_id=release_id, problems=problems,
                             requests={"total": fetcher.requests, "by_host": fetcher.by_host}, log_lines=log_lines)
    log(f"done: {len(long):,} rows, {fetcher.requests} requests, problems: {problems or 'none'}")
    (out_dir / "build.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return manifest


def dumps(obj) -> str:
    return json.dumps(obj, indent=1, default=str)
