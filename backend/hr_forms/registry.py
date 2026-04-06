"""
Resolve paths to HR form assets (official PDFs + internal DOCX).

Convention:
  - Set HR_FORM_ASSETS_DIR in .env to an absolute path, or rely on default
    backend/hr_form_assets/forms/
  - Copy files from your official downloads using names in catalog.json "files"
    (e.g. ny_ls54_en.pdf, uscis_i9_es.pdf).

I-9 EN: still falls back to backend/hr_compliance.resolve_i9_template_path() when
no file is present under HR_FORM_ASSETS_DIR for uscis_i9 / en.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"


def _default_assets_dir() -> Path:
    env = (os.environ.get("HR_FORM_ASSETS_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "hr_form_assets" / "forms"


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    with open(_CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def list_forms(lane: Optional[str] = None) -> list[dict[str, Any]]:
    """All catalog entries, optionally filtered by lane (employee_w2 | contractor_1099)."""
    forms = load_catalog().get("forms") or []
    if not lane:
        return list(forms)
    return [x for x in forms if x.get("lane") == lane]


def get_form_def(form_id: str) -> Optional[dict[str, Any]]:
    for f in load_catalog().get("forms") or []:
        if f.get("id") == form_id:
            return f
    return None


def resolve_form_asset_path(form_id: str, locale: str) -> Optional[str]:
    """
    Return absolute path to template if file exists, else None.
    locale: en | es | bilingual
    """
    d = get_form_def(form_id)
    if not d:
        return None
    files = d.get("files") or {}
    name = files.get(locale)
    if not name:
        return None
    base = _default_assets_dir() / name
    if base.is_file():
        return str(base)

    # I-9 English: reuse existing repo template when canonical name not copied yet
    if form_id == "uscis_i9" and locale == "en":
        try:
            from backend.hr_compliance import resolve_i9_template_path

            legacy = resolve_i9_template_path()
            if legacy and os.path.isfile(legacy):
                return legacy
        except Exception:
            pass

    return None


def list_missing_assets(form_id: Optional[str] = None) -> list[dict[str, str]]:
    """Which catalog files are still not on disk (for admin diagnostics)."""
    missing: list[dict[str, str]] = []
    if form_id:
        one = get_form_def(form_id)
        forms = [one] if one else []
    else:
        forms = list_forms()
    for d in forms:
        fid = str(d.get("id") or "")
        for loc, fname in (d.get("files") or {}).items():
            if resolve_form_asset_path(fid, loc) is None:
                missing.append({"form_id": fid, "locale": loc, "expected_file": fname})
    return missing
