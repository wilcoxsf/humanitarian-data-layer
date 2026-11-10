import sys
import types

import pandas as pd

from hdl import build, release, schema


def test_plugin_registers_sources_and_specs():
    mod = types.ModuleType("fake_overlay")
    mod.SOURCES = {"fake_internal": lambda ctx: ([], {})}
    mod.SPECS = {"fake_internal": {"name": "x", "publish": False, "classification": "irc_internal"}}
    sys.modules["fake_overlay"] = mod
    try:
        assert build.load_plugin("fake_overlay") == ["fake_internal"]
        assert build.classification(build.load_sources()["fake_internal"]) == "irc_internal"
    finally:
        build.SOURCES.pop("fake_internal", None)
        build.EXTRA_SPECS.pop("fake_internal", None)


def test_public_bundle_excludes_non_public_rows(tmp_path, areas):
    rows = []
    for sid, cls in (("worldpop", "public"), ("hapi", "restricted"), ("irc_fy25", "irc_internal")):
        rows.append({"area_id": "TST.0.TS", "iso3": "TST", "admin_level": 0, "pcode": "TS", "source_id": sid,
                     "domain": "population", "metric": "m", "value": 1.0, "period": "2025", "status": "sourced",
                     "classification": cls})
    long = schema.frame(rows)
    sources = {"worldpop": {"publish": True}, "hapi": {"publish": False}, "irc_fy25": {"publish": False},
               "geography": {"publish": True}}
    results = [{"iso3": "TST", "areas": pd.DataFrame(areas.drop(columns="geometry")), "gdf": areas, "frames": [], "info": {}}]
    release.write(results, long, tmp_path, sources, release_id="t", problems=[], requests={"total": 0}, log_lines=[])
    pub = pd.read_parquet(tmp_path / "public" / "hdl_long.parquet")
    full = pd.read_parquet(tmp_path / "full" / "hdl_long.parquet")
    assert pub.source_id.tolist() == ["worldpop"]
    assert sorted(full.classification) == ["irc_internal", "public", "restricted"]
