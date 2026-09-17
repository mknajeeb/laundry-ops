"""WF clean-reset epoch + ops maintenance gate (org-scoped system_settings).

Physical scan history (``upload_batch_scan_events``, ``rinse_bag_scan_events``,
``upload_batches`` and children) survives a WF clean reset — strategy D. Nothing
deletes it. Resurrection is blocked *logically* instead: evidence stamped before
``wf_reset_epoch_at`` must never re-admit a service cycle, order instance, or
completion.

Business time contract: the epoch is persisted as an ISO **UTC** instant
(infrastructure clock). Every business comparison in here converts both sides to
America/New_York first — never UTC-vs-naive-ET.

Settings keys (org-scoped, ``system_settings``):
  ``wf_reset_epoch_at``  — ISO UTC timestamp, written only on a real --apply
  ``wf_ops_maintenance`` — "1" / "0"
  ``wf_trusted_baseline``— JSON metadata written after a good baseline scrape
"""

from __future__ import annotations

import hmac
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.rinse_folding_et import ET
from backend.ta_helpers import table_exists, table_has_column

UTC = ZoneInfo("UTC")

WF_RESET_EPOCH_KEY = "wf_reset_epoch_at"
WF_OPS_MAINTENANCE_KEY = "wf_ops_maintenance"
WF_TRUSTED_BASELINE_KEY = "wf_trusted_baseline"

# Operator-supplied token that lets the one authorized baseline scrape run while
# WF ops maintenance is on. Empty env => no token is valid (fail closed).
BASELINE_RESET_AUTH_ENV = "WF_BASELINE_RESET_AUTH"

# Scan evidence whose timestamp cannot be established is treated as pre-epoch.
EVIDENCE_UNDATED_IS_PRE_EPOCH = True

_CACHE_TTL_SECONDS = 60.0
_cache_lock = threading.Lock()
_epoch_cache: dict[int, tuple[float, datetime | None]] = {}


class WfOpsMaintenanceActive(RuntimeError):
    """Raised when a WF mutation is attempted while ops maintenance is on."""


def invalidate_wf_reset_epoch_cache(organization_id: int | None = None) -> None:
    with _cache_lock:
        if organization_id is None:
            _epoch_cache.clear()
        else:
            _epoch_cache.pop(int(organization_id), None)


def _settings_available(cursor) -> bool:
    return table_exists(cursor, "system_settings") and table_has_column(
        cursor, "system_settings", "organization_id"
    )


def get_setting(cursor, organization_id: int, key: str) -> str | None:
    if not _settings_available(cursor):
        return None
    cursor.execute(
        "SELECT svalue FROM system_settings WHERE organization_id = %s AND skey = %s LIMIT 1",
        (int(organization_id), key),
    )
    row = cursor.fetchone()
    if not row:
        return None
    val = row.get("svalue") if isinstance(row, dict) else row[0]
    return None if val is None else str(val)


def set_setting(cursor, organization_id: int, key: str, value: str) -> None:
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE svalue=VALUES(svalue)
        """,
        (int(organization_id), key, str(value)),
    )


def parse_epoch_value(raw: Any) -> datetime | None:
    """Parse the stored epoch into an aware UTC datetime."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=UTC) if raw.tzinfo is None else raw.astimezone(UTC)
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def get_wf_reset_epoch_at(
    cursor, organization_id: int, *, use_cache: bool = True
) -> datetime | None:
    """Aware UTC epoch for this org, or None when no WF clean reset has run."""
    org = int(organization_id)
    now = time.monotonic()
    if use_cache:
        with _cache_lock:
            hit = _epoch_cache.get(org)
        if hit is not None and (now - hit[0]) < _CACHE_TTL_SECONDS:
            return hit[1]
    epoch = parse_epoch_value(get_setting(cursor, org, WF_RESET_EPOCH_KEY))
    with _cache_lock:
        _epoch_cache[org] = (now, epoch)
    return epoch


def set_wf_reset_epoch_at(
    cursor, organization_id: int, when: datetime | None = None
) -> datetime:
    """Persist the epoch as ISO UTC. Only a real --apply may call this."""
    org = int(organization_id)
    epoch = when or datetime.now(timezone.utc)
    epoch = epoch.replace(tzinfo=UTC) if epoch.tzinfo is None else epoch.astimezone(UTC)
    set_setting(cursor, org, WF_RESET_EPOCH_KEY, epoch.isoformat())
    invalidate_wf_reset_epoch_cache(org)
    return epoch


def epoch_scan_wall(epoch: datetime | None) -> datetime | None:
    """Epoch as a naive America/New_York wall value.

    ``rinse_bag_scan_events.scanned_at_parsed`` and ``cycle_anchor_at`` are naive
    ET wall (see ``backend/rinse_scan_time.py``). Comparisons and baseline
    anchors must use this form, never the raw UTC instant.
    """
    if epoch is None:
        return None
    return epoch.astimezone(ET).replace(tzinfo=None)


def _as_et_aware(dt: datetime, kind: str) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(ET)
    if kind == "system":
        return dt.replace(tzinfo=UTC).astimezone(ET)
    # Rinse scan / cycle anchor naive values are ET wall.
    return dt.replace(tzinfo=ET)


def evidence_on_or_after_epoch(
    dt: datetime | None,
    epoch: datetime | None,
    *,
    kind: str = "scan",
) -> bool:
    """True when this evidence may still drive WF lifecycle after the reset.

    ``kind="scan"`` treats naive values as ET wall (portal scan chronology);
    ``kind="system"`` treats naive values as UTC (scrape/DB clocks).
    """
    if epoch is None:
        return True
    if dt is None or not isinstance(dt, datetime):
        return not EVIDENCE_UNDATED_IS_PRE_EPOCH
    return _as_et_aware(dt, kind) >= epoch.astimezone(ET)


def epoch_sql_predicate(
    cursor,
    organization_id: int,
    *,
    column: str = "scanned_at_parsed",
) -> tuple[str, tuple[Any, ...]]:
    """Authoritative SQL fragment for WF reset epoch fencing.

    Returns ``(\" AND <column> >= %s\", (wall,))`` or ``(\"\", ())`` when no
    epoch is set. All production scan SELECTs that can drive lifecycle should
    use this (or ``filter_scan_event_rows``) rather than ad-hoc date checks.
    """
    wall = epoch_scan_wall(get_wf_reset_epoch_at(cursor, int(organization_id)))
    if wall is None:
        return "", ()
    return f" AND `{column}` >= %s", (wall,)


def filter_scan_event_rows(
    cursor,
    organization_id: int,
    rows: Any,
    *,
    ts_key: str = "scanned_at_parsed",
) -> list[dict[str, Any]]:
    """Drop pre-epoch scan rows. Central post-fetch fence for loaders.

    Prefer ``epoch_sql_predicate`` in SQL when possible; use this when a loader
    already fetched rows or when the timestamp column name varies.
    """
    epoch = get_wf_reset_epoch_at(cursor, int(organization_id))
    out: list[dict[str, Any]] = []
    for row in rows or []:
        d = dict(row) if not isinstance(row, dict) else row
        ts = d.get(ts_key)
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if ts.tzinfo is not None:
                    ts = ts.astimezone(ET).replace(tzinfo=None)
            except ValueError:
                ts = None
        if evidence_on_or_after_epoch(
            ts if isinstance(ts, datetime) else None, epoch, kind="scan"
        ):
            out.append(d)
    return out


def assert_production_scan_mutation_uses_epoch_fence() -> None:
    """Documentation hook for offline scripts — prefer filtered loaders.

    Offline recovery must call ``fetch_persistent_scan_events_*`` or
    ``load_canonical_completions_v2`` (both epoch-fenced). Direct SQL against
    ``rinse_bag_scan_events`` / ``upload_batch_scan_events`` for lifecycle
    mutation is forbidden in production paths.
    """
    return None


def epoch_lower_bound_et(
    cursor,
    organization_id: int,
    floor: datetime | None = None,
) -> datetime | None:
    """Return max(floor, epoch_wall) for time-window scan queries.

    When an epoch is set, no scan before the epoch may participate in
    operational membership/completion windows — even if the window's natural
    start is earlier.
    """
    wall = epoch_scan_wall(get_wf_reset_epoch_at(cursor, int(organization_id)))
    if wall is None:
        return floor
    if floor is None:
        return wall
    return max(floor, wall)


def require_offline_recovery_authorization(*, apply: bool) -> None:
    """Block offline lifecycle recovery apply unless explicitly unlocked.

    Dry-run is always allowed. Apply requires ``WF_OFFLINE_RECOVERY_OK=1``.
    Production scrape/API paths never call this; they use epoch-fenced loaders.
    """
    if not apply:
        return
    if os.getenv("WF_OFFLINE_RECOVERY_OK", "").strip() != "1":
        raise RuntimeError(
            "Offline lifecycle recovery --apply is blocked. "
            "Set WF_OFFLINE_RECOVERY_OK=1 only for authorized one-shot recovery. "
            "Normal post-reset ops must not re-run historical scan recovery."
        )


def get_wf_ops_maintenance(cursor, organization_id: int) -> bool:
    raw = get_setting(cursor, organization_id, WF_OPS_MAINTENANCE_KEY)
    return str(raw or "").strip() in ("1", "true", "True", "yes", "on")


def set_wf_ops_maintenance(cursor, organization_id: int, enabled: bool) -> bool:
    set_setting(
        cursor, organization_id, WF_OPS_MAINTENANCE_KEY, "1" if enabled else "0"
    )
    return bool(enabled)


def get_wf_trusted_baseline(cursor, organization_id: int) -> dict[str, Any] | None:
    raw = get_setting(cursor, organization_id, WF_TRUSTED_BASELINE_KEY)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def set_wf_trusted_baseline(
    cursor, organization_id: int, metadata: dict[str, Any]
) -> dict[str, Any]:
    body = dict(metadata or {})
    body.setdefault("recorded_at_utc", datetime.now(timezone.utc).isoformat())
    set_setting(
        cursor, organization_id, WF_TRUSTED_BASELINE_KEY, json.dumps(body, default=str)
    )
    return body


def baseline_auth_token_valid(token: str | None) -> bool:
    """Constant-time check against ``WF_BASELINE_RESET_AUTH``. Fail closed."""
    expected = str(os.getenv(BASELINE_RESET_AUTH_ENV) or "").strip()
    supplied = str(token or "").strip()
    if not expected or not supplied:
        return False
    return hmac.compare_digest(expected, supplied)


def wf_ops_mutation_gate(
    cursor,
    organization_id: int,
    *,
    allow_baseline_token: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Non-raising form for job entry points. Returns (allowed, detail).

    Maintenance is an explicit operator opt-in. If the flag cannot be read the
    gate stays open: an unreadable setting must not take the scraper down.
    """
    org = int(organization_id)
    try:
        maintenance = get_wf_ops_maintenance(cursor, org)
    except Exception as exc:
        return True, {
            "organization_id": org,
            "reason": "maintenance_unreadable",
            "error": str(exc),
        }
    if not maintenance:
        return True, {"organization_id": org, "reason": "maintenance_off"}
    if baseline_auth_token_valid(allow_baseline_token):
        return True, {
            "organization_id": org,
            "reason": "baseline_auth_accepted",
            "maintenance": True,
        }
    return False, {
        "organization_id": org,
        "reason": "wf_ops_maintenance_active",
        "maintenance": True,
        "hint": (
            f"set {BASELINE_RESET_AUTH_ENV} and pass the baseline token to run the "
            "single authorized baseline scrape"
        ),
    }


def assert_wf_ops_mutation_allowed(
    cursor,
    organization_id: int,
    *,
    allow_baseline_token: str | None = None,
) -> None:
    allowed, detail = wf_ops_mutation_gate(
        cursor, organization_id, allow_baseline_token=allow_baseline_token
    )
    if not allowed:
        raise WfOpsMaintenanceActive(
            f"WF ops maintenance active for organization_id={detail['organization_id']}; "
            "mutation refused"
        )
