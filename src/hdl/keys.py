"""API keys: environment variable first (GitHub Actions secrets), then ~/.config/<service>/.env (local).

Values are never logged or written to receipts; URLs that carry a key are stored redacted.
"""

from __future__ import annotations

import os
from pathlib import Path


def get(name: str, service: str) -> str:
    v = os.environ.get(name, "").strip()
    if v:
        return v
    p = Path.home() / ".config" / service / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            k, _, val = line.partition("=")
            if k.strip() == name:
                return val.strip().strip('"').strip("'")
    return ""
