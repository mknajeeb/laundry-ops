"""Embed organization logos in server-generated HTML (paystubs, receipts)."""

from __future__ import annotations

import base64
import os
import re
from typing import Optional

_ORG_LOGO_PATH_RE = re.compile(
    r"/media/org-logos/(?P<org_id>\d+)/(?P<filename>[a-f0-9]{32}\.(?:png|jpg|jpeg|webp|gif))",
    re.I,
)
_MIME_BY_EXT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


def _local_org_logo_root() -> str:
    root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "instance", "org_logos")
    )
    os.makedirs(root, exist_ok=True)
    return root


def _bytes_to_data_uri(data: bytes, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    mime = _MIME_BY_EXT.get(ext, "image/png")
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def read_org_logo_data_uri(organization_id: int, filename: str) -> Optional[str]:
    """Load org logo bytes from local disk or Azure blob."""
    safe = os.path.basename(filename)
    if not _ORG_LOGO_PATH_RE.match(f"/media/org-logos/{organization_id}/{safe}"):
        return None
    root = os.path.join(_local_org_logo_root(), str(int(organization_id)))
    fp = os.path.join(root, safe)
    if os.path.isfile(fp):
        with open(fp, "rb") as fh:
            return _bytes_to_data_uri(fh.read(), safe)
    try:
        from backend.app import _ensure_blob_container

        cc = _ensure_blob_container()
        if cc is not None:
            blob_name = f"org-logos/{int(organization_id)}/{safe}"
            data = cc.get_blob_client(blob_name).download_blob().readall()
            return _bytes_to_data_uri(data, safe)
    except Exception:
        pass
    return None


def org_logo_data_uri_from_url(logo_url: Optional[str]) -> Optional[str]:
    if not logo_url:
        return None
    m = _ORG_LOGO_PATH_RE.search(str(logo_url))
    if not m:
        return None
    return read_org_logo_data_uri(int(m.group("org_id")), m.group("filename"))


def organization_logo_img_html(
    organization_id: int,
    logo_url: Optional[str],
    company_name: str,
    *,
    height_px: int = 44,
    css_class: str = "paystub-logo",
) -> str:
    data_uri = org_logo_data_uri_from_url(logo_url)
    if not data_uri:
        slug_match = _ORG_LOGO_PATH_RE.search(str(logo_url or ""))
        if slug_match:
            data_uri = read_org_logo_data_uri(
                int(slug_match.group("org_id")), slug_match.group("filename")
            )
    if data_uri:
        return (
        f'<img src="{data_uri}" alt="{company_name}" class="{css_class}" '
        f'style="height: {height_px}px; width: auto; display: block;" />'
        )
    from backend.veewash_branding import veewash_logo_img_html

    return veewash_logo_img_html(height_px=height_px, css_class=css_class)
