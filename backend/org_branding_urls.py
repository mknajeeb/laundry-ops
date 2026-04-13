"""Rewrite org logo URLs in JSON responses when PUBLIC_API_BASE is set.

DB rows from local dev often store http://127.0.0.1:8000/...; browsers on HTTPS
cannot load those (mixed content). Replacing the origin with PUBLIC_API_BASE
points clients at the real API without a manual DB migration.
"""

from __future__ import annotations

import os
from typing import Optional

_LOCAL_DEV_PREFIXES = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://localhost",
)


def rewrite_org_logo_url_for_client(url: Optional[str]) -> Optional[str]:
    if url is None:
        return None
    s = str(url).strip()
    if not s:
        return url
    pub = (os.getenv("PUBLIC_API_BASE") or "").strip().rstrip("/")
    if not pub:
        return s
    for bad in _LOCAL_DEV_PREFIXES:
        if s.startswith(bad):
            rest = s[len(bad) :]
            if not rest.startswith("/"):
                rest = "/" + rest
            return f"{pub}{rest}"
    return s
