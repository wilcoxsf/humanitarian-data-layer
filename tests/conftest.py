"""Tiny synthetic country 'TST': admin0 = 4x2 degree box, two admin1 halves, four admin2 quarters."""

import json
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import box, mapping

from hdl import geography
from hdl.context import Context, Country
from hdl.fetch import Fetcher


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def _feat(geom, **props):
    return {"type": "Feature", "geometry": mapping(geom), "properties": props}


@pytest.fixture
def cod_zip(tmp_path):
    a0 = [_feat(box(0, 0, 4, 2), adm0_name="Testland", adm0_pcode="TS", valid_on="2025-01-01")]
    a1 = [_feat(box(0, 0, 2, 2), adm1_name="West", adm1_pcode="TS01", adm0_pcode="TS", valid_on="2025-01-01"),
          _feat(box(2, 0, 4, 2), adm1_name="East", adm1_pcode="TS02", adm0_pcode="TS", valid_on="2025-01-01")]
    a2 = [_feat(box(0, 0, 1, 2), adm2_name="West A", adm2_pcode="TS0101", adm1_pcode="TS01", valid_on="2025-01-01"),
          _feat(box(1, 0, 2, 2), adm2_name="West B", adm2_pcode="TS0102", adm1_pcode="TS01", valid_on="2025-01-01"),
          _feat(box(2, 0, 3, 2), adm2_name="East A", adm2_pcode="TS0201", adm1_pcode="TS02", valid_on="2025-01-01"),
          _feat(box(3, 0, 4, 2), adm2_name="East B", adm2_pcode="TS0202", adm1_pcode="TS02", valid_on="2025-01-01")]
    p = tmp_path / "tst_admin_boundaries.geojson.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("tst_admin0.geojson", json.dumps(_fc(a0)))
        zf.writestr("tst_admin1.geojson", json.dumps(_fc(a1)))
        zf.writestr("tst_admin2.geojson", json.dumps(_fc(a2)))
        zf.writestr("tst_admin2_em.geojson", json.dumps(_fc(a2)))  # edge-matched copy must be ignored
    return p


@pytest.fixture
def areas(cod_zip) -> gpd.GeoDataFrame:
    return geography.load(cod_zip, "TST")


@pytest.fixture
def ctx(areas, tmp_path) -> Context:
    return Context(Country("TST", "TS", "999", "Testland"), areas, Fetcher(tmp_path / "raw", offline=True), tmp_path, {})
