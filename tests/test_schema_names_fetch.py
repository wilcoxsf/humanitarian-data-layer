import json

import pytest

from hdl import schema
from hdl.fetch import Fetcher, OfflineMiss, receipt_path
from hdl.names import NameMatcher, norm


def _row(**kw):
    base = {"iso3": "TST", "admin_level": 0, "pcode": "TS", "source_id": "x", "domain": "need", "metric": "m",
            "breakdown": "", "value": 1.0, "period": "2026", "status": "sourced"}
    return {**base, **kw}


def test_validate_ok_and_problems():
    assert schema.validate(schema.frame([_row()])) == []
    p = schema.validate(schema.frame([_row(), _row(value=2.0)]))
    assert any("share a key" in x for x in p)
    p = schema.validate(schema.frame([_row(status="guess")]))
    assert any("unknown status" in x for x in p)
    p = schema.validate(schema.frame([_row(value=None)]))
    assert any("no numeric or text value" in x for x in p)
    assert schema.validate(schema.frame([_row(value=None, status="missing")])) == []
    assert schema.validate(schema.frame([_row(value=None, value_text="Not set")])) == []


def test_breakdown_skips_empty():
    assert schema.breakdown(sector="Health", phase="", x=None) == "sector=Health"


def test_norm_and_matcher(areas):
    assert norm("Ségou Région") == "segou"
    m = NameMatcher(areas, "TST", "dhs", 1)
    assert m.match("..West") == ("TS01", "name")  # DHS second-level dots are punctuation to norm()
    assert m.match("west") == ("TS01", "name")
    assert m.match("North") == (None, "unmatched")


def test_fetch_offline_and_cache(tmp_path):
    f = Fetcher(tmp_path, offline=True)
    with pytest.raises(OfflineMiss):
        f.download("https://example.org/a.csv", "a.csv")
    (tmp_path / "a.csv").write_text("x\n1\n")
    receipt_path(tmp_path / "a.csv").write_text(json.dumps({"url": "u"}))
    assert f.download("https://example.org/a.csv", "a.csv").read_text() == "x\n1\n"
    assert f.requests == 0
