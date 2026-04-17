"""Tenant-level toggles for ops UI (scan, browse list, dryer QR). Stored in system_settings."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from backend.ta_helpers import table_exists


KEY_SCAN = "ops_scan_lookup_enabled"
KEY_BROWSE = "ops_browse_list_enabled"
KEY_DRYER = "ops_dryer_qr_scan_enabled"


def _truthy(raw: Any, default: bool = True) -> bool:
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if s == "":
        return default
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


def get_ops_ui_flags(cursor, organization_id: int) -> dict[str, bool]:
    """Defaults keep current behaviour when settings are missing."""
    return {
        "scan_lookup_enabled": _truthy(_get_setting(cursor, organization_id, KEY_SCAN), True),
        "browse_list_enabled": _truthy(_get_setting(cursor, organization_id, KEY_BROWSE), True),
        "dryer_qr_scan_enabled": _truthy(_get_setting(cursor, organization_id, KEY_DRYER), True),
    }


def put_ops_ui_flags(cursor, organization_id: int, payload: Mapping[str, Any]) -> dict[str, bool]:
    """Persist known keys; omit absent keys."""
    if "scan_lookup_enabled" in payload:
        _set_setting(
            cursor,
            organization_id,
            KEY_SCAN,
            "1" if _truthy(payload.get("scan_lookup_enabled"), True) else "0",
        )
    if "browse_list_enabled" in payload:
        _set_setting(
            cursor,
            organization_id,
            KEY_BROWSE,
            "1" if _truthy(payload.get("browse_list_enabled"), True) else "0",
        )
    if "dryer_qr_scan_enabled" in payload:
        _set_setting(
            cursor,
            organization_id,
            KEY_DRYER,
            "1" if _truthy(payload.get("dryer_qr_scan_enabled"), True) else "0",
        )
    return get_ops_ui_flags(cursor, organization_id)
