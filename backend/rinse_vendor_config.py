"""
Map Washpro organization → Rinse vendor account (washpro | veewash) and build scrape env.

Server / local API: set in repo-root `.env` (Flask), e.g.:
  RINSE_WASHPRO_ORG_IDS=1
  RINSE_VEEWASH_ORG_IDS=2
  RINSE_WASHPRO_STORAGE_STATE=/home/site/rinse-tenants/washpro/rinse-auth.json
  RINSE_VEEWASH_STORAGE_STATE=/home/site/rinse-tenants/veewash/rinse-auth.json
  RINSE_WASHPRO_EMAIL=...
  RINSE_WASHPRO_PASSWORD=...
  RINSE_VEEWASH_EMAIL=...
  RINSE_VEEWASH_PASSWORD=...
  RINSE_WASHPRO_TICKETS_URL=https://www.rinse.com/cleanertickets/...
  RINSE_VEEWASH_TICKETS_URL=...

Legacy single-tenant (fallback): RINSE_STORAGE_STATE, RINSE_EMAIL, RINSE_PASSWORD, RINSE_TICKETS_URL
"""

from __future__ import annotations

import os
import re
from pathlib import Path

VALID_VENDORS = frozenset({"washpro", "veewash"})


def _parse_id_set(raw: str | None) -> set[int]:
    out: set[int] = set()
    if not raw:
        return out
    for part in re.split(r"[,;\s]+", str(raw).strip()):
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return out


def _parse_slug_set(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {p.strip().lower() for p in re.split(r"[,;\s]+", str(raw).strip()) if p.strip()}


def resolve_rinse_vendor(
    organization_id: int | None,
    *,
    organization_slug: str | None = None,
    organization_name: str | None = None,
    override: str | None = None,
) -> str:
    """Return 'washpro' or 'veewash' for this organization."""
    if override:
        v = str(override).strip().lower()
        if v in VALID_VENDORS:
            return v
        raise ValueError(f"rinse_vendor must be washpro or veewash, got: {override}")

    oid = int(organization_id) if organization_id is not None else None
    washpro_ids = _parse_id_set(os.getenv("RINSE_WASHPRO_ORG_IDS"))
    veewash_ids = _parse_id_set(os.getenv("RINSE_VEEWASH_ORG_IDS"))

    if oid is not None:
        if oid in washpro_ids:
            return "washpro"
        if oid in veewash_ids:
            return "veewash"

    slug = (organization_slug or "").strip().lower()
    washpro_slugs = _parse_slug_set(os.getenv("RINSE_WASHPRO_ORG_SLUGS"))
    veewash_slugs = _parse_slug_set(os.getenv("RINSE_VEEWASH_ORG_SLUGS"))
    if slug and slug in washpro_slugs:
        return "washpro"
    if slug and slug in veewash_slugs:
        return "veewash"

    name = (organization_name or "").lower()
    if "veewash" in name or "vee wash" in name:
        return "veewash"
    if "washpro" in name or "wash pro" in name:
        return "washpro"

    default = (os.getenv("RINSE_VENDOR_DEFAULT") or "washpro").strip().lower()
    return default if default in VALID_VENDORS else "washpro"


def _vendor_env_key(vendor: str, suffix: str) -> str | None:
    """RINSE_WASHPRO_STORAGE_STATE etc., then legacy RINSE_STORAGE_STATE."""
    v = vendor.upper()
    prefixed = (os.getenv(f"RINSE_{v}_{suffix}") or "").strip()
    if prefixed:
        return prefixed
    if suffix == "STORAGE_STATE":
        return (os.getenv("RINSE_STORAGE_STATE") or "").strip() or None
    if suffix == "EMAIL":
        return (os.getenv("RINSE_EMAIL") or "").strip() or None
    if suffix == "PASSWORD":
        return (os.getenv("RINSE_PASSWORD") or "").strip() or None
    if suffix == "TICKETS_URL":
        return (os.getenv("RINSE_TICKETS_URL") or "").strip() or None
    return None


def _resolve_storage_path(vendor: str, raw: str, scraper_dir: Path | None) -> str:
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    base = scraper_dir if scraper_dir else Path(__file__).resolve().parent.parent / "scripts" / "rinse-cleanertickets"
    # tenants/washpro/rinse-auth.json under scraper dir
    if raw.startswith("./tenants/") or raw.startswith("tenants/"):
        return str((base / raw).resolve())
    return str((base / raw).resolve())


def rinse_scrape_env_for_vendor(vendor: str, scraper_dir: Path | None = None) -> dict[str, str]:
    """Env vars passed to Node scrape.mjs subprocess for one Rinse vendor account."""
    v = vendor.strip().lower()
    if v not in VALID_VENDORS:
        raise ValueError(f"Unknown rinse vendor: {vendor}")

    out: dict[str, str] = {"RINSE_VENDOR": v}

    storage = _vendor_env_key(v, "STORAGE_STATE")
    if storage:
        out["RINSE_STORAGE_STATE"] = _resolve_storage_path(v, storage, scraper_dir)

    email = _vendor_env_key(v, "EMAIL")
    if email:
        out["RINSE_EMAIL"] = email

    password = _vendor_env_key(v, "PASSWORD")
    if password:
        out["RINSE_PASSWORD"] = password

    url = _vendor_env_key(v, "TICKETS_URL")
    if url:
        out["RINSE_TICKETS_URL"] = url

    return out


def rinse_scrape_env_for_organization(
    organization_id: int,
    *,
    organization_slug: str | None = None,
    organization_name: str | None = None,
    override_vendor: str | None = None,
    scraper_dir: Path | None = None,
) -> tuple[str, dict[str, str]]:
    vendor = resolve_rinse_vendor(
        organization_id,
        organization_slug=organization_slug,
        organization_name=organization_name,
        override=override_vendor,
    )
    return vendor, rinse_scrape_env_for_vendor(vendor, scraper_dir)


def vendor_auth_status(vendor: str, scraper_dir: Path | None = None) -> dict:
    env = rinse_scrape_env_for_vendor(vendor, scraper_dir)
    path = env.get("RINSE_STORAGE_STATE", "")
    p = Path(path) if path else None
    return {
        "vendor": vendor,
        "storage_state": path,
        "storage_exists": bool(p and p.is_file() and p.stat().st_size > 8),
        "has_email": bool(env.get("RINSE_EMAIL")),
        "has_tickets_url": bool(env.get("RINSE_TICKETS_URL")),
    }


def diagnose_vendors(scraper_dir: Path | None = None) -> dict:
    return {
        "washpro": vendor_auth_status("washpro", scraper_dir),
        "veewash": vendor_auth_status("veewash", scraper_dir),
    }
