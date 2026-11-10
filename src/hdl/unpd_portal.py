"""UN DESA Population Division data portal API, for pulls the public CSV files do not cover.

Needs a free bearer token: email population@un.org with the subject "Data Portal Token Request", then save it
as UNPD_API_TOKEN in ~/.config/unpd/.env (or a GitHub Actions secret). Without it every call raises.

    from hdl.unpd_portal import data, indicators
    indicators(fetcher)                                   # catalogue (open, no token)
    data(fetcher, [2, 5], ["706", "728"], 2015, 2030)     # rows as dicts
"""

from __future__ import annotations

import hashlib

from .fetch import Fetcher
from .keys import get

API = "https://population.un.org/dataportalapi/api/v1"


def indicators(fetcher: Fetcher) -> list[dict]:
    out, url, page = [], f"{API}/indicators?pageSize=100", 1
    while url and page <= 10:
        d = fetcher.get_json(url, f"unpd_portal/indicators_p{page}.json")
        out += d.get("data", [])
        url, page = d.get("nextPage"), page + 1
    return out


def data(fetcher: Fetcher, indicator_ids: list[int], locations: list[str], start: int, end: int,
         max_pages: int = 50) -> list[dict]:
    token = get("UNPD_API_TOKEN", "unpd")
    if not token:
        raise RuntimeError("UNPD_API_TOKEN not set: email population@un.org, subject 'Data Portal Token Request'")
    ids, locs = ",".join(map(str, indicator_ids)), ",".join(map(str, locations))
    url = f"{API}/data/indicators/{ids}/locations/{locs}/start/{start}/end/{end}?pageSize=1000&format=json"
    tag = hashlib.md5(url.encode()).hexdigest()[:10]
    out, page = [], 1
    while url and page <= max_pages:
        d = fetcher.get_json(url, f"unpd_portal/data_{tag}_p{page}.json", headers={"Authorization": f"Bearer {token}"})
        out += d.get("data", [])
        url, page = d.get("nextPage"), page + 1
    return out
