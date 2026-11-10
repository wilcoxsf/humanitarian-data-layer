"""Matching source area names to pinned admin areas when a source has no pcodes (DHS, GRID3, ...).

Order: explicit alias table (config/name_aliases.csv) -> normalized exact name -> unmatched.
No fuzzy matching: a wrong match is worse than an honest 'unmatched'.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

ALIASES = Path(__file__).resolve().parent / "config" / "name_aliases.csv"
DROP_WORDS = {"state", "governorate", "department", "departement", "region", "province", "district", "lga", "county"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(w for w in s.split() if w not in DROP_WORDS)


def load_aliases(path: Path = ALIASES) -> dict[tuple[str, str, str], str]:
    out = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[(r["iso3"], r["source_id"], norm(r["source_name"]))] = r["pcode"]
    return out


class NameMatcher:
    def __init__(self, areas, iso3: str, source_id: str, level: int, parent_pcode: str | None = None):
        a = areas[areas.admin_level == level]
        if parent_pcode is not None:
            a = a[a.parent_pcode == parent_pcode]
        self.iso3, self.source_id, self.level = iso3, source_id, level
        self.by_name: dict[str, list[str]] = {}
        for pc, nm in zip(a.pcode, a.name, strict=True):
            self.by_name.setdefault(norm(nm), []).append(pc)
        self.aliases = load_aliases()

    def match(self, label: str) -> tuple[str | None, str]:
        """(pcode, how) where how is alias, name, ambiguous or unmatched."""
        key = norm(label)
        pc = self.aliases.get((self.iso3, self.source_id, key)) or self.aliases.get((self.iso3, "*", key))
        if pc:
            return pc, "alias"
        hits = self.by_name.get(key, [])
        if len(hits) == 1:
            return hits[0], "name"
        return None, "ambiguous" if hits else "unmatched"
