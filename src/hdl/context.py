"""What every source adapter gets: the country, its pinned areas, a fetcher and settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd

from .fetch import Fetcher


@dataclass
class Country:
    iso3: str
    iso2: str
    m49: str
    name: str
    dhs_code: str = ""

    @property
    def iso(self) -> str:
        return self.iso3.lower()


@dataclass
class Context:
    country: Country
    areas: gpd.GeoDataFrame
    fetcher: Fetcher
    work_dir: Path
    settings: dict = field(default_factory=dict)

    # ---- area lookups used by every adapter ------------------------------
    def __post_init__(self):
        a = self.areas
        self._by_pcode = {(int(lvl), pc): aid for lvl, pc, aid in zip(a.admin_level, a.pcode, a.area_id, strict=True)}
        self._any_pcode = {pc: (int(lvl), aid) for lvl, pc, aid in zip(a.admin_level, a.pcode, a.area_id, strict=True)}
        self._name = dict(zip(a.area_id, a.name, strict=True))
        self.national_id = a.loc[a.admin_level == 0, "area_id"].iloc[0]
        self.national_pcode = a.loc[a.admin_level == 0, "pcode"].iloc[0]

    def match(self, level: int, pcode: str) -> tuple[str, str]:
        """(area_id, geo_match) for a source pcode at a stated level."""
        if level == 0:
            return self.national_id, "national"
        aid = self._by_pcode.get((int(level), str(pcode).strip()))
        return (aid, "exact") if aid else ("", "unmatched")

    def name(self, aid: str) -> str:
        return self._name.get(aid, "")

    def levels(self) -> list[int]:
        return sorted(int(x) for x in self.areas.admin_level.unique())
