"""Checkout-only tenant settings (not lifecycle / performance)."""

from __future__ import annotations

from typing import Any, Optional

from backend.ta_helpers import table_exists

KEY_CHECKOUT_INCLUDE_COMPLETED = "checkout_include_completed_if_at_vendor"
# Legacy key (Washpro manual rack rule) — read if new key unset
KEY_MANUAL_CHECKOUT_ACCEPT_COMPLETED = "manual_checkout_accept_completed_without_later_rack"

WASHPRO_SLUG = "washpro"
VEEWASH_SLUG = "veewash"
_AT_VENDOR_DEFAULT_SLUGS = frozenset({WASHPRO_SLUG, VEEWASH_SLUG})


def _truthy(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if s in {"0", "false", "off", "no", "disabled"}:
        return False
    if s in {"1", "true", "on", "yes", "enabled"}:
        return True
    return default


def _get_setting(cursor, organization_id: int, key: str) -> Optional[str]:
    if not table_exists(cursor, "system_settings"):
        return None
    cursor.execute(
        "SELECT svalue FROM system_settings WHERE organization_id=%s AND skey=%s LIMIT 1",
        (int(organization_id), key),
    )
    row = cursor.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        v = row.get("svalue")
    else:
        v = row[0] if row else None
    return None if v is None else str(v)


def _set_setting(cursor, organization_id: int, key: str, value: str) -> None:
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, value),
    )


def organization_slug(cursor, organization_id: int) -> str:
    if not table_exists(cursor, "organizations"):
        return ""
    cursor.execute(
        "SELECT slug FROM organizations WHERE id = %s LIMIT 1",
        (int(organization_id),),
    )
    row = cursor.fetchone()
    if not isinstance(row, dict):
        return ""
    return str(row.get("slug") or "").strip().lower()


def is_washpro_organization(cursor, organization_id: int) -> bool:
    return organization_slug(cursor, organization_id) == WASHPRO_SLUG


def is_veewash_organization(cursor, organization_id: int) -> bool:
    return organization_slug(cursor, organization_id) == VEEWASH_SLUG


def _default_checkout_include_completed(cursor, organization_id: int) -> bool:
    return organization_slug(cursor, organization_id) in _AT_VENDOR_DEFAULT_SLUGS


def get_checkout_include_completed_if_at_vendor(
    cursor,
    organization_id: int,
) -> bool:
    """
    Checkout-only: include completed/CLEAN bags if still at vendor (in upload/scrape).

    Explicit DB value wins. When unset: enabled for Washpro and VeeWash slugs.
    Falls back to legacy manual_checkout_accept_completed_without_later_rack key.
    """
    explicit = _get_setting(cursor, organization_id, KEY_CHECKOUT_INCLUDE_COMPLETED)
    if explicit is not None:
        return _truthy(explicit, False)
    legacy = _get_setting(cursor, organization_id, KEY_MANUAL_CHECKOUT_ACCEPT_COMPLETED)
    if legacy is not None:
        return _truthy(legacy, False)
    return _default_checkout_include_completed(cursor, organization_id)


def set_checkout_include_completed_if_at_vendor(
    cursor,
    organization_id: int,
    enabled: bool,
) -> None:
    _set_setting(
        cursor,
        int(organization_id),
        KEY_CHECKOUT_INCLUDE_COMPLETED,
        "1" if enabled else "0",
    )


def checkout_at_vendor_override_active(
    cursor,
    organization_id: int,
) -> bool:
    """True when checkout should treat completed bags as eligible if still at vendor."""
    return get_checkout_include_completed_if_at_vendor(cursor, int(organization_id))


# Back-compat aliases
get_manual_checkout_accept_completed_without_later_rack = get_checkout_include_completed_if_at_vendor
set_manual_checkout_accept_completed_without_later_rack = set_checkout_include_completed_if_at_vendor


def washpro_manual_checkout_override_active(
    cursor,
    organization_id: int,
    *,
    is_auto_scrape: bool = False,
) -> bool:
    """Deprecated: use checkout_at_vendor_override_active + workflow branch in eligibility."""
    if is_auto_scrape:
        return checkout_at_vendor_override_active(cursor, organization_id)
    return checkout_at_vendor_override_active(cursor, organization_id)
