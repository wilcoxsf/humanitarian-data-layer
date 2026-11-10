import pandas as pd
import pytest

from hdl import schema
from hdl.sources import hapi


def _df(rows, cols):
    return pd.DataFrame([dict(zip(cols, r, strict=True)) for r in rows], dtype=str)


NEEDS_COLS = ["location_code", "admin_level", "admin1_code", "admin1_name", "admin2_code", "admin2_name", "sector_name",
              "category", "population_status", "population", "reference_period_start", "reference_period_end"]


def test_read_csv_drops_hxl_row(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("location_code,population\n#country+code,#population\nTST,5\n", encoding="utf-8")
    df = hapi.read_csv(p)
    assert len(df) == 1 and df.population[0] == "5"


def test_needs_dedupes_identical_and_derives_admin1(ctx):
    rows = [
        ["TST", "0", "", "", "", "", "Health", "total", "INN", "100", "2026-01-01", "2026-12-31"],
        ["TST", "0", "", "", "", "", "Health", "total", "INN", "100", "2026-01-01", "2026-12-31"],  # identical duplicate
        ["TST", "2", "TS01", "West", "TS0101", "West A", "Health", "total", "INN", "30", "2026-01-01", "2026-12-31"],
        ["TST", "2", "TS01", "West", "TS0102", "West B", "Health", "total", "INN", "20", "2026-01-01", "2026-12-31"],
        ["TST", "2", "TS02", "East", "TS0201", "East A", "Health", "total", "INN", "40", "2026-01-01", "2026-12-31"],
        ["TST", "2", "TS02", "East", "XX9999", "Lost", "Health", "total", "INN", "5", "2026-01-01", "2026-12-31"],
        ["TST", "2", "TS02", "East", "TS0202", "East B", "Health", "female", "INN", "999", "2026-01-01", "2026-12-31"],
    ]
    R, qa = hapi.Rows(ctx), {}
    hapi.needs(_df(rows, NEEDS_COLS), R, {"resources": {}}, qa)
    df = schema.frame(R.out())
    assert schema.validate(df) == []
    nat = df[(df.admin_level == 0)]
    assert nat.value.tolist() == [100.0]  # not 200
    west = df[(df.admin_level == 1) & (df.pcode == "TS01")].iloc[0]
    assert west.value == 50 and west.status == "partial" and "90%" in west.note  # 90 of 100 matched in admin2
    assert df[df.pcode == "XX9999"].geo_match.tolist() == ["unmatched"]
    assert 999.0 not in df.value.tolist()  # non-total categories are not mixed in


IPC_COLS = ["location_code", "admin_level", "admin1_code", "admin1_name", "admin2_code", "admin2_name",
            "provider_admin1_name", "provider_admin2_name", "ipc_phase", "ipc_type", "population_in_phase",
            "population_fraction_in_phase", "reference_period_start", "reference_period_end"]


def test_ipc_sums_units_and_recomputes_share(ctx):
    P = ("2026-07-01", "2026-09-30")
    rows = [
        ["TST", "2", "TS01", "West", "TS0101", "West A", "West", "West A urban", "all", "current", "100", "1", *P],
        ["TST", "2", "TS01", "West", "TS0101", "West A", "West", "West A rural", "all", "current", "300", "1", *P],
        ["TST", "2", "TS01", "West", "TS0101", "West A", "West", "West A urban", "3+", "current", "50", "0.5", *P],
        ["TST", "2", "TS01", "West", "TS0101", "West A", "West", "West A rural", "3+", "current", "30", "0.1", *P],
        ["TST", "2", "", "", "", "", "", "Coastal pastoral", "3+", "current", "7", "0.2", *P],
    ]
    R, qa = hapi.Rows(ctx), {}
    hapi.ipc(_df(rows, IPC_COLS), R, {"resources": {}}, qa)
    df = schema.frame(R.out())
    a = df[(df.pcode == "TS0101") & (df.breakdown == "ipc_type=current;phase=3+")].set_index("metric")
    assert a.loc["population_in_ipc_phase", "value"] == 80
    assert a.loc["share_in_ipc_phase", "value"] == pytest.approx(0.2)
    u = df[df.pcode.str.startswith("IPC:")]
    assert u.geo_match.unique().tolist() == ["unmatched"] and u.value.tolist() == [7.0]
