import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hdl import geography
from hdl.zonal import raster_total, zonal_sum


def test_load_builds_ids_and_hierarchy(areas):
    assert sorted(areas.admin_level.unique()) == [0, 1, 2]
    assert len(areas) == 1 + 2 + 4  # the _em duplicate layer is ignored
    row = areas.set_index("area_id").loc["TST.2.TS0102"]
    assert row["parent_area_id"] == "TST.1.TS01" and row["name"] == "West B"
    q = geography.qa(areas)
    assert q["errors"] == [] and q["areas_by_level"] == {0: 1, 1: 2, 2: 4}


def test_qa_warns_on_orphans_and_catches_duplicates(areas):
    bad = areas[areas.area_id != "TST.1.TS01"]
    q = geography.qa(bad)
    assert q["errors"] == [] and any("parent is not in the parent layer" in w for w in q["warnings"])
    import pandas as pd
    dup = pd.concat([areas, areas.iloc[[1]]])
    assert any("duplicate area_id" in e for e in geography.qa(dup)["errors"])


@pytest.fixture
def raster(tmp_path):
    # 0.5 degree pixels over the 4x2 box, value 1 everywhere, one nodata pixel.
    a = np.ones((4, 8), dtype="float32")
    a[0, 0] = -99999
    p = tmp_path / "r.tif"
    with rasterio.open(p, "w", driver="GTiff", height=4, width=8, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(0, 2, 0.5, 0.5), nodata=-99999) as dst:
        dst.write(a, 1)
    return p


def test_zonal_sums_add_up(areas, raster):
    s = zonal_sum(raster, areas)
    assert s["TST.0.TS"] == pytest.approx(31)  # 32 pixels minus one nodata, never counted as zero-or-value
    assert s[[a for a in s.index if a.startswith("TST.2.")]].sum() == pytest.approx(s["TST.0.TS"])
    assert s["TST.2.TS0101"] == pytest.approx(7)
    assert raster_total(raster) == pytest.approx(31)


def test_zonal_fractional_coverage(tmp_path, areas):
    # 1-degree pixels offset by half a degree: boundary pixels are split between neighbours.
    a = np.full((2, 5), 10, dtype="float32")
    p = tmp_path / "off.tif"
    with rasterio.open(p, "w", driver="GTiff", height=2, width=5, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(-0.5, 2, 1, 1), nodata=-1) as dst:
        dst.write(a, 1)
    s = zonal_sum(p, areas)
    assert s["TST.2.TS0101"] == pytest.approx(20)  # x 0..1 covers half of two pixel columns = one column x 2 rows x 10
    assert s["TST.0.TS"] == pytest.approx(80)       # x 0..4 covers 4 of the 5 pixel columns
