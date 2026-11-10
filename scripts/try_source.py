"""Developer helper: run one source adapter for one country and print a summary.

    .venv/Scripts/python.exe scripts/try_source.py hapi SOM [--offline]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hdl import (
    build,  # noqa: E402
    schema,  # noqa: E402
)

src, iso3 = sys.argv[1], sys.argv[2].upper()
offline = "--offline" in sys.argv
ctx = build.make_context(iso3, offline=offline, max_requests=60)
rows, info = build.SOURCES[src](ctx)
df = schema.frame(rows)
print(json.dumps(info.get("qa", {}), indent=1, default=str)[:3000])
print("validate:", schema.validate(df) or "ok")
print(df.groupby(["domain", "metric", "status", "geo_match"]).size().to_string())
print("requests:", ctx.fetcher.requests, ctx.fetcher.by_host)
