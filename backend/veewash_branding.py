"""Shared VeeWash branding helpers for server-generated HTML documents."""

from __future__ import annotations

import base64
import os

_LOGO_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "assets", "veewash-logo.png")
)
_cached_data_uri: str | None = None


def veewash_logo_data_uri() -> str:
    global _cached_data_uri
    if _cached_data_uri is None:
        with open(_LOGO_PATH, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode("ascii")
        _cached_data_uri = f"data:image/png;base64,{encoded}"
    return _cached_data_uri


def veewash_logo_img_html(*, height_px: int = 48, css_class: str = "vw-logo") -> str:
    return (
        f'<img src="{veewash_logo_data_uri()}" alt="VeeWash" class="{css_class}" '
        f'style="height:{height_px}px;width:auto;object-fit:contain;display:block;" />'
    )
