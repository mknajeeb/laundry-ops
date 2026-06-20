"""Tests for embedded org logos in print HTML."""

import os
import tempfile

from backend.org_logo_embed import (
    organization_logo_img_html,
    org_logo_data_uri_from_url,
    read_org_logo_data_uri,
)


def test_org_logo_data_uri_from_media_path():
    with tempfile.TemporaryDirectory() as tmp:
        org_id = 3
        filename = "abcdef0123456789abcdef0123456789.png"
        root = os.path.join(tmp, str(org_id))
        os.makedirs(root)
        png_bytes = b"\x89PNG\r\n\x1a\n"
        with open(os.path.join(root, filename), "wb") as fh:
            fh.write(png_bytes)

        import backend.org_logo_embed as mod

        old_root = mod._local_org_logo_root
        mod._local_org_logo_root = lambda: tmp
        try:
            uri = read_org_logo_data_uri(org_id, filename)
            assert uri and uri.startswith("data:image/png;base64,")
            url = f"https://api.example.com/media/org-logos/{org_id}/{filename}"
            assert org_logo_data_uri_from_url(url) == uri
            html = organization_logo_img_html(org_id, url, "VeeWash", height_px=40)
            assert "data:image/png;base64," in html
            assert "paystub-logo" in html
        finally:
            mod._local_org_logo_root = old_root
