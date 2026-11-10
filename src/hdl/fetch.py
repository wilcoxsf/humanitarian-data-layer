"""Bounded, cached HTTP downloads with a receipt for every file.

Rules this module enforces:
- every request counts against a per-run cap, and requests are spaced out;
- 401, 403 and 429 stop the run (no retry, no workaround);
- a file already on disk with a receipt is reused unless refresh is asked for;
- offline mode never touches the network.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "humanitarian-data-layer/2.0 (+https://github.com/wilcoxsf/humanitarian-data-layer)"


class UpstreamBlocked(RuntimeError):
    """The upstream said no (401/403/429). Stop and report; do not work around it."""


class RequestCapReached(RuntimeError):
    pass


class OfflineMiss(RuntimeError):
    pass


class IncompleteDownload(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def receipt_path(path: Path) -> Path:
    return path.with_name(path.name + ".receipt.json")


class Fetcher:
    def __init__(self, raw_dir: Path, *, max_requests: int = 400, delay: float = 1.0,
                 refresh: bool = False, offline: bool = False, timeout: float = 180.0):
        self.raw_dir = Path(raw_dir)
        self.max_requests = max_requests
        self.delay = delay
        self.refresh = refresh
        self.offline = offline
        self.timeout = timeout
        self.requests = 0
        self.by_host: dict[str, int] = {}
        self._last = 0.0

    # -- low level -------------------------------------------------------
    def _open(self, url: str, headers: dict | None = None, shown: str | None = None):
        if self.offline:
            raise OfflineMiss(f"offline mode and not cached: {shown or url}")
        if self.requests >= self.max_requests:
            raise RequestCapReached(f"request cap {self.max_requests} reached before {shown or url}")
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self.requests += 1
        host = urllib.parse.urlparse(url).netloc
        self.by_host[host] = self.by_host.get(host, 0) + 1
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                raise UpstreamBlocked(f"{e.code} from {host} for {shown or url}") from None
            raise RuntimeError(f"HTTP {e.code} from {host} for {shown or url}") from None
        finally:
            self._last = time.monotonic()
        return resp

    # -- public ------------------------------------------------------------
    def download(self, url: str, dest: Path, *, headers: dict | None = None, meta: dict | None = None,
                 receipt_url: str | None = None) -> Path:
        """receipt_url: what to record instead of url when url carries a secret (e.g. a token query parameter)."""
        shown = receipt_url or url
        """Download url to dest (under raw_dir if relative). Returns the path. Writes dest.receipt.json."""
        dest = Path(dest)
        if not dest.is_absolute():
            dest = self.raw_dir / dest
        rec = receipt_path(dest)
        if dest.exists() and rec.exists() and not self.refresh:
            try:
                same_url = json.loads(rec.read_text(encoding="utf-8")).get("url") == shown
            except (ValueError, OSError):
                same_url = False
            if same_url or self.offline:  # a cached file from a different URL (e.g. new indicators) is refetched
                return dest
        if self.offline:
            raise OfflineMiss(f"offline mode and not cached: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        for attempt in (1, 2):  # one retry, only for a transfer that ended short
            with self._open(url, headers, shown) as resp, open(tmp, "wb") as out:
                status = resp.status
                info = {k.lower(): v for k, v in resp.headers.items()}
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            expected = int(info["content-length"]) if info.get("content-length", "").isdigit() else None
            got = tmp.stat().st_size
            if expected is None or got == expected:
                break
            tmp.unlink(missing_ok=True)
            if attempt == 2:
                raise IncompleteDownload(f"{shown}: got {got} bytes, server said {expected}")
        tmp.replace(dest)
        receipt = {
            "url": shown,
            "path": dest.name,
            "bytes": dest.stat().st_size,
            "sha256": sha256_file(dest),
            "http_status": status,
            "content_type": info.get("content-type"),
            "last_modified": info.get("last-modified"),
            "etag": info.get("etag"),
            "retrieved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }
        if meta:
            receipt["meta"] = meta
        rec.write_text(json.dumps(receipt, indent=1), encoding="utf-8")
        return dest

    def get_json(self, url: str, dest: Path, **kw):
        path = self.download(url, dest, **kw)
        return json.loads(path.read_text(encoding="utf-8"))


def read_receipt(path: Path) -> dict | None:
    rec = receipt_path(Path(path))
    if rec.exists():
        return json.loads(rec.read_text(encoding="utf-8"))
    return None
