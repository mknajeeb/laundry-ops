"""Tenant-scoped configurable folding exception rules (system_settings)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from backend.ta_helpers import table_exists

KEY_EXCEPTION_RULES_JSON = "rinse_folding_exception_rules_json"
KEY_RULES_SAVED_AT = "rinse_folding_exception_rules_saved_at"
KEY_LAST_RECOMPUTE_AT = "rinse_folding_last_recompute_at"

DEFAULT_MIN_DURATION_MINUTES = 10
DEFAULT_MAX_DURATION_MINUTES = 240

# Multiple folding scans (evaluated last)
MULTIPLE_FOLDING_WARNING_EARLIEST = "warning_use_earliest_folding"
MULTIPLE_FOLDING_WARNING_LATEST = "warning_use_latest_folding"
MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION = "exception"
# Legacy aliases
MULTIPLE_FOLDING_BEHAVIOR_WARNING_EARLIEST = MULTIPLE_FOLDING_WARNING_EARLIEST
LEGACY_MF_WARNING_DEFAULT = "warning_use_earliest_default"

# Multiple clean scans
MULTIPLE_CLEAN_WARNING_EARLIEST = "warning_use_earliest_clean"
MULTIPLE_CLEAN_WARNING_LATEST = "warning_use_latest_clean"
MULTIPLE_CLEAN_BEHAVIOR_EXCEPTION = "exception"


@dataclass(frozen=True)
class FoldingExceptionRules:
    rule_missing_clean: bool
    rule_missing_folding: bool
    rule_clean_before_folding: bool
    rule_min_duration_enabled: bool
    rule_max_duration_enabled: bool
    min_duration_minutes: int
    max_duration_minutes: int
    multiple_clean_scans_behavior: str
    rule_overlap_invalid_timing: bool
    multiple_folding_scans_behavior: str

    @property
    def rule_multiple_folding_scans(self) -> bool:
        return self.multiple_folding_scans_behavior == MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION

    @property
    def multiple_clean_scans_as_exception(self) -> bool:
        return self.multiple_clean_scans_behavior == MULTIPLE_CLEAN_BEHAVIOR_EXCEPTION

    @property
    def min_duration_seconds(self) -> int:
        if not self.rule_min_duration_enabled:
            return 0
        return max(0, int(self.min_duration_minutes)) * 60

    @property
    def max_duration_seconds(self) -> int | None:
        if not self.rule_max_duration_enabled:
            return None
        m = int(self.max_duration_minutes)
        if m <= 0:
            return None
        return m * 60


def default_exception_rules_dict() -> dict[str, Any]:
    return {
        "rule_missing_clean": True,
        "rule_missing_folding": True,
        "rule_clean_before_folding": True,
        "rule_min_duration_enabled": True,
        "rule_max_duration_enabled": True,
        "min_duration_minutes": DEFAULT_MIN_DURATION_MINUTES,
        "max_duration_minutes": DEFAULT_MAX_DURATION_MINUTES,
        "multiple_clean_scans_behavior": MULTIPLE_CLEAN_WARNING_EARLIEST,
        "multiple_clean_scans_as_exception": False,
        "rule_overlap_invalid_timing": True,
        "multiple_folding_scans_behavior": MULTIPLE_FOLDING_WARNING_EARLIEST,
        "rule_multiple_folding_scans": False,
        "overlap_timing_help": (
            "Flags folding_end before folding_start, non-positive duration, or end clean "
            "not strictly after folding start. Does not check cross-bag user overlap yet."
        ),
        "max_duration_help": "Maximum applies only when maximum duration rule is enabled.",
        "priority_order": [
            "FOLDING_DURATION_TOO_SHORT",
            "FOLDING_DURATION_TOO_LONG",
            "MISSING_CLEAN",
            "MISSING_FOLDING",
            "CLEAN_BEFORE_FOLDING",
            "MULTIPLE_CLEAN_SCANS",
            "MULTIPLE_FOLDING_SCANS",
        ],
        "priority_note": (
            "When several rules apply, the primary exception_code uses this order. "
            "Lower-priority scan conditions (e.g. multiple folding scans) may appear as "
            "secondary warnings on the record."
        ),
    }


def _bool_val(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def _int_val(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _normalize_scan_behavior(
    raw: Any,
    *,
    legacy_exception_bool: bool | None,
    earliest: str,
    latest: str,
    exception: str,
    legacy_warning: str | None = None,
) -> str:
    if raw is not None and str(raw).strip():
        b = str(raw).strip().lower()
        if b in (exception, "exception"):
            return exception
        if b in (latest, "warning_use_latest_clean", "warning_use_latest_folding"):
            return latest
        if b in (
            earliest,
            legacy_warning or "",
            LEGACY_MF_WARNING_DEFAULT,
            "warning_use_earliest_default",
            "warning_use_earliest_clean",
            "warning_use_earliest_folding",
        ):
            return earliest
    if legacy_exception_bool:
        return exception
    return earliest


def _multiple_folding_behavior(src: dict[str, Any], *, user_payload: dict[str, Any] | None = None) -> str:
    payload = user_payload if user_payload is not None else src
    legacy = None
    if "rule_multiple_folding_scans" in payload:
        legacy = _bool_val(payload.get("rule_multiple_folding_scans"), False)
    raw_behavior = (
        payload.get("multiple_folding_scans_behavior")
        if "multiple_folding_scans_behavior" in payload
        else None
    )
    return _normalize_scan_behavior(
        raw_behavior,
        legacy_exception_bool=legacy,
        earliest=MULTIPLE_FOLDING_WARNING_EARLIEST,
        latest=MULTIPLE_FOLDING_WARNING_LATEST,
        exception=MULTIPLE_FOLDING_BEHAVIOR_EXCEPTION,
        legacy_warning=LEGACY_MF_WARNING_DEFAULT,
    )


def _multiple_clean_behavior(src: dict[str, Any], *, user_payload: dict[str, Any] | None = None) -> str:
    payload = user_payload if user_payload is not None else src
    legacy = None
    if "multiple_clean_scans_as_exception" in payload:
        legacy = _bool_val(payload.get("multiple_clean_scans_as_exception"), False)
    key = "multiple_clean_scans_behavior"
    raw = payload.get(key) if key in payload else None
    return _normalize_scan_behavior(
        raw,
        legacy_exception_bool=legacy,
        earliest=MULTIPLE_CLEAN_WARNING_EARLIEST,
        latest=MULTIPLE_CLEAN_WARNING_LATEST,
        exception=MULTIPLE_CLEAN_BEHAVIOR_EXCEPTION,
    )


def parse_exception_rules_payload(data: dict[str, Any] | None) -> FoldingExceptionRules:
    base = default_exception_rules_dict()
    user = data or {}
    src = {**base, **user}
    return FoldingExceptionRules(
        rule_missing_clean=_bool_val(src.get("rule_missing_clean"), True),
        rule_missing_folding=_bool_val(src.get("rule_missing_folding"), True),
        rule_clean_before_folding=_bool_val(src.get("rule_clean_before_folding"), True),
        rule_min_duration_enabled=_bool_val(src.get("rule_min_duration_enabled"), True),
        rule_max_duration_enabled=_bool_val(src.get("rule_max_duration_enabled"), True),
        min_duration_minutes=max(
            0, _int_val(src.get("min_duration_minutes"), DEFAULT_MIN_DURATION_MINUTES)
        ),
        max_duration_minutes=_int_val(src.get("max_duration_minutes"), DEFAULT_MAX_DURATION_MINUTES),
        multiple_clean_scans_behavior=_multiple_clean_behavior(src, user_payload=user),
        rule_overlap_invalid_timing=_bool_val(src.get("rule_overlap_invalid_timing"), True),
        multiple_folding_scans_behavior=_multiple_folding_behavior(src, user_payload=user),
    )


def _get_setting(cursor, organization_id: int, key: str) -> str | None:
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


def get_folding_exception_rules(cursor, organization_id: int) -> dict[str, Any]:
    raw = _get_setting(cursor, int(organization_id), KEY_EXCEPTION_RULES_JSON)
    if not raw or not str(raw).strip():
        return default_exception_rules_dict()
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return default_exception_rules_dict()
    except json.JSONDecodeError:
        return default_exception_rules_dict()
    out = default_exception_rules_dict()
    out.update({k: parsed[k] for k in out if k in parsed})
    for k, v in parsed.items():
        if k not in out and not k.endswith("_help"):
            out[k] = v
    return out


def get_folding_exception_rules_typed(
    cursor, organization_id: int
) -> FoldingExceptionRules:
    return parse_exception_rules_payload(get_folding_exception_rules(cursor, organization_id))


def _rules_to_stored_dict(rules: FoldingExceptionRules) -> dict[str, Any]:
    stored = default_exception_rules_dict()
    stored.update(
        {
            "rule_missing_clean": rules.rule_missing_clean,
            "rule_missing_folding": rules.rule_missing_folding,
            "rule_clean_before_folding": rules.rule_clean_before_folding,
            "rule_min_duration_enabled": rules.rule_min_duration_enabled,
            "rule_max_duration_enabled": rules.rule_max_duration_enabled,
            "min_duration_minutes": rules.min_duration_minutes,
            "max_duration_minutes": rules.max_duration_minutes,
            "multiple_clean_scans_behavior": rules.multiple_clean_scans_behavior,
            "multiple_clean_scans_as_exception": rules.multiple_clean_scans_as_exception,
            "rule_overlap_invalid_timing": rules.rule_overlap_invalid_timing,
            "multiple_folding_scans_behavior": rules.multiple_folding_scans_behavior,
            "rule_multiple_folding_scans": rules.rule_multiple_folding_scans,
        }
    )
    return stored


def put_folding_exception_rules(
    cursor, organization_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    current = get_folding_exception_rules(cursor, organization_id)
    merged = {**current, **(payload or {})}
    rules = parse_exception_rules_payload(merged)
    stored = _rules_to_stored_dict(rules)
    _set_setting(cursor, int(organization_id), KEY_EXCEPTION_RULES_JSON, json.dumps(stored))
    from datetime import datetime

    _set_setting(
        cursor,
        int(organization_id),
        KEY_RULES_SAVED_AT,
        datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    )
    return get_folding_exception_rules_with_meta(cursor, organization_id)


def get_folding_rules_meta(cursor, organization_id: int) -> dict[str, Any]:
    saved = _get_setting(cursor, int(organization_id), KEY_RULES_SAVED_AT)
    recomputed = _get_setting(cursor, int(organization_id), KEY_LAST_RECOMPUTE_AT)
    recompute_needed = False
    if saved and recomputed:
        recompute_needed = str(saved) > str(recomputed)
    elif saved:
        recompute_needed = True
    return {
        "rules_saved_at": saved,
        "last_recompute_at": recomputed,
        "recompute_needed": recompute_needed,
    }


def normalize_rules_api_dict(rules: dict[str, Any] | None) -> dict[str, Any]:
    parsed = parse_exception_rules_payload(rules)
    out = default_exception_rules_dict()
    out.update(rules or {})
    stored = _rules_to_stored_dict(parsed)
    out.update(stored)
    return out


def get_folding_exception_rules_with_meta(
    cursor, organization_id: int
) -> dict[str, Any]:
    out = normalize_rules_api_dict(get_folding_exception_rules(cursor, organization_id))
    out.update(get_folding_rules_meta(cursor, organization_id))
    return out


def mark_folding_recompute_applied(cursor, organization_id: int) -> None:
    from datetime import datetime

    _set_setting(
        cursor,
        int(organization_id),
        KEY_LAST_RECOMPUTE_AT,
        datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    )
