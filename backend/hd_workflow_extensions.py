"""HD workflow extensions: fresh start, exclude/restore/delete, delivery dates.

Operational HD state lives in hd_day_bag_production. Shared Rinse scan evidence is
never deleted by these helpers.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.business_time import business_now, business_today
from backend.management_rinse_hd import (
    ACTION_ADMIT,
    ATTR_SOURCE_SCAN,
    HD_WORKFLOW_ACTIVATION_DATE,
    PROD_NOT_RECORDED,
    STATUS_AWAITING_ENTRY,
    STATUS_COMPLETE,
    STATUS_PENDING_WASH,
    STATUS_WASHED,
    WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED,
    _as_naive,
    _batch_user_names,
    _compact_order,
    _is_workflow_complete_row,
    _load_candidate_events_for_bags,
    _load_production_by_bag,
    _load_user_maps,
    _norm_bag,
    _persist_scan_state_for_admitted,
    business_date_of,
    derive_workflow_status,
    ensure_management_hd_columns,
    resolve_order_state,
)
from backend.ta_helpers import invalidate_schema_cache, table_exists, table_has_column

STATUS_EXCLUDED = "excluded"

_HD_SETTINGS_TABLE = "hd_workflow_org_settings"


def ensure_hd_workflow_settings_table(cursor) -> None:
    if table_exists(cursor, _HD_SETTINGS_TABLE):
        return
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_HD_SETTINGS_TABLE} (
          organization_id INT NOT NULL PRIMARY KEY,
          fresh_start_at DATETIME NULL,
          fresh_start_audit_json JSON NULL,
          updated_at DATETIME NULL
        )
        """
    )
    invalidate_schema_cache()


def ensure_hd_exclude_columns(cursor) -> None:
    ensure_management_hd_columns(cursor)
    if not table_exists(cursor, "hd_day_bag_production"):
        return
    altered = False
    specs = (
        ("excluded_at", "DATETIME NULL"),
        ("excluded_by_user_id", "INT NULL"),
        ("excluded_by_name", "VARCHAR(255) NULL"),
        ("excluded_reason", "VARCHAR(64) NULL"),
        ("excluded_note", "TEXT NULL"),
        ("excluded_from_status", "VARCHAR(32) NULL"),
    )
    for col, ddl in specs:
        if table_has_column(cursor, "hd_day_bag_production", col):
            continue
        try:
            cursor.execute(f"ALTER TABLE hd_day_bag_production ADD COLUMN {col} {ddl}")
            altered = True
        except Exception as exc:
            if "Duplicate column" not in str(exc):
                raise
            altered = True
    if altered:
        invalidate_schema_cache()


def load_hd_workflow_settings(cursor, organization_id: int) -> dict[str, Any]:
    ensure_hd_workflow_settings_table(cursor)
    org = int(organization_id)
    cursor.execute(
        f"""
        SELECT organization_id, fresh_start_at, fresh_start_audit_json, updated_at
        FROM {_HD_SETTINGS_TABLE}
        WHERE organization_id = %s
        LIMIT 1
        """,
        (org,),
    )
    row = cursor.fetchone()
    if not row:
        return {"organization_id": org, "fresh_start_at": None, "fresh_start_audit_json": None}
    audit = row.get("fresh_start_audit_json")
    if isinstance(audit, str):
        try:
            audit = json.loads(audit)
        except json.JSONDecodeError:
            audit = None
    fresh = row.get("fresh_start_at")
    if isinstance(fresh, datetime):
        fresh = fresh.replace(tzinfo=None)
    return {
        "organization_id": org,
        "fresh_start_at": fresh,
        "fresh_start_audit_json": audit,
        "updated_at": row.get("updated_at"),
    }


def hd_workflow_cutoff(cursor, organization_id: int) -> tuple[date, datetime | None]:
    """Return (activation_date_floor, fresh_start_at) for scan/state gating."""
    settings = load_hd_workflow_settings(cursor, organization_id)
    fresh_at = _as_naive(settings.get("fresh_start_at"))
    activation = HD_WORKFLOW_ACTIVATION_DATE
    if fresh_at is not None:
        fresh_day = business_date_of(fresh_at) or activation
        return max(activation, fresh_day), fresh_at
    return activation, None


def on_or_after_workflow_cutoff(
    dt: Any,
    activation: date | None,
    *,
    fresh_start_at: datetime | None = None,
) -> bool:
    naive = _as_naive(dt)
    if naive is None:
        return False
    if fresh_start_at is not None and naive < fresh_start_at:
        return False
    if activation is None:
        return True
    day = business_date_of(naive)
    return day is not None and day >= activation


def _load_delivery_dates_for_bags(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
) -> dict[str, date]:
    ids = [_norm_bag(b) for b in bag_ids if _norm_bag(b)]
    if not ids:
        return {}
    out: dict[str, date] = {}
    org = int(organization_id)
    if table_exists(cursor, "rinse_cleaner_ticket_presence"):
        ph = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT bag_id, estimated_delivery_date
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s AND bag_id IN ({ph})
            """,
            (org, *ids),
        )
        for row in cursor.fetchall() or []:
            bid = _norm_bag(row.get("bag_id"))
            raw = row.get("estimated_delivery_date")
            if not bid or raw is None:
                continue
            if isinstance(raw, date):
                out[bid] = raw
            else:
                try:
                    out[bid] = date.fromisoformat(str(raw)[:10])
                except ValueError:
                    pass
    still = [b for b in ids if b not in out]
    if still and table_exists(cursor, "rinse_shift_monitor_day_bags"):
        ph = ",".join(["%s"] * len(still))
        cursor.execute(
            f"""
            SELECT bag_id, bag_snapshot_json
            FROM rinse_shift_monitor_day_bags
            WHERE organization_id = %s AND bag_id IN ({ph})
            ORDER BY shift_date_et DESC
            """,
            (org, *still),
        )
        for row in cursor.fetchall() or []:
            bid = _norm_bag(row.get("bag_id"))
            if not bid or bid in out:
                continue
            snap = row.get("bag_snapshot_json")
            if isinstance(snap, str):
                try:
                    snap = json.loads(snap)
                except json.JSONDecodeError:
                    snap = {}
            if not isinstance(snap, dict):
                continue
            raw = snap.get("estimated_delivery_date") or snap.get("delivery_date")
            if raw is None:
                continue
            try:
                out[bid] = date.fromisoformat(str(raw)[:10])
            except ValueError:
                pass
    return out


def attach_delivery_dates(
    cursor,
    organization_id: int,
    orders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not orders:
        return orders
    edd_map = _load_delivery_dates_for_bags(
        cursor, organization_id, [o.get("bag_id") for o in orders]
    )
    out: list[dict[str, Any]] = []
    for order in orders:
        row = dict(order)
        bid = _norm_bag(row.get("bag_id"))
        edd = edd_map.get(bid)
        row["delivery_date_et"] = edd.isoformat() if isinstance(edd, date) else None
        out.append(row)
    return out


def _workflow_status_counts(cursor, organization_id: int) -> dict[str, int]:
    ensure_hd_exclude_columns(cursor)
    if not table_exists(cursor, "hd_day_bag_production"):
        return {}
    org = int(organization_id)
    cursor.execute(
        """
        SELECT COALESCE(workflow_status, '') AS wf, COUNT(*) AS n
        FROM hd_day_bag_production
        WHERE organization_id = %s
          AND COALESCE(workflow_status, '') <> %s
        GROUP BY COALESCE(workflow_status, '')
        """,
        (org, WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED),
    )
    return {str(r.get("wf") or ""): int(r.get("n") or 0) for r in (cursor.fetchall() or [])}


def _reset_row_to_pending_wash(cursor, row_id: int) -> None:
    cursor.execute(
        """
        UPDATE hd_day_bag_production SET
          workflow_status = %s,
          status = %s,
          washed_at = NULL,
          washed_by_user_id = NULL,
          washed_by_name_snapshot = NULL,
          washed_by_override_name = NULL,
          washed_date_et = NULL,
          folded_at = NULL,
          folded_by_user_id = NULL,
          folded_by_name_snapshot = NULL,
          folded_by_override_name = NULL,
          folded_date_et = NULL,
          washed_attribution_source = NULL,
          folded_attribution_source = NULL,
          management_completed_at = NULL,
          management_completed_by_user_id = NULL,
          management_completed_by_name = NULL,
          completion_source = NULL,
          total_items = NULL,
          revenue = NULL,
          excluded_at = NULL,
          excluded_by_user_id = NULL,
          excluded_by_name = NULL,
          excluded_reason = NULL,
          excluded_note = NULL,
          excluded_from_status = NULL,
          version = version + 1
        WHERE id = %s
        """,
        (STATUS_PENDING_WASH, PROD_NOT_RECORDED, int(row_id)),
    )


def _quarantine_row(cursor, row_id: int) -> None:
    cursor.execute(
        """
        UPDATE hd_day_bag_production SET
          workflow_status = %s,
          version = version + 1
        WHERE id = %s
        """,
        (WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED, int(row_id)),
    )


def run_hd_fresh_start(
    cursor,
    organization_id: int,
    *,
    actor_user_id: int | None = None,
    selected_date_et: date | None = None,
) -> dict[str, Any]:
    """Fresh start: retain current Pending Wash only; quarantine all other HD workflow rows."""
    from backend.management_rinse_hd import build_rinse_hd_day

    ensure_hd_exclude_columns(cursor)
    ensure_hd_workflow_settings_table(cursor)
    org = int(organization_id)
    day = selected_date_et or business_today()
    before_counts = _workflow_status_counts(cursor, org)

    pending_day = build_rinse_hd_day(cursor, org, day, status=STATUS_PENDING_WASH)
    retained_ids = sorted(
        {_norm_bag(o.get("bag_id")) for o in (pending_day.get("orders") or []) if _norm_bag(o.get("bag_id"))}
    )

    fresh_at = business_now()
    fresh_naive = fresh_at.replace(tzinfo=None) if getattr(fresh_at, "tzinfo", None) else fresh_at

    cursor.execute(
        f"""
        INSERT INTO {_HD_SETTINGS_TABLE} (organization_id, fresh_start_at, updated_at)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
          fresh_start_at = VALUES(fresh_start_at),
          updated_at = VALUES(updated_at)
        """,
        (org, fresh_naive, fresh_naive),
    )

    if not table_exists(cursor, "hd_day_bag_production"):
        audit = {
            "before": before_counts,
            "retained_pending_wash_ids": retained_ids,
            "quarantined": 0,
            "reset_pending": 0,
        }
        cursor.execute(
            f"""
            UPDATE {_HD_SETTINGS_TABLE}
            SET fresh_start_audit_json = %s
            WHERE organization_id = %s
            """,
            (json.dumps(audit), org),
        )
        return {
            "ok": True,
            "fresh_start_at": fresh_naive.isoformat(sep=" "),
            "before": before_counts,
            "retained_pending_wash_ids": retained_ids,
            "after": {"pending_wash": len(retained_ids), "awaiting_fold": 0, "awaiting_entry": 0, "complete": 0, "excluded": 0},
            "quarantined": 0,
            "reset_pending": 0,
        }

    cursor.execute(
        """
        SELECT id, bag_id, workflow_status
        FROM hd_day_bag_production
        WHERE organization_id = %s
          AND COALESCE(workflow_status, '') <> %s
        """,
        (org, WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED),
    )
    rows = cursor.fetchall() or []
    retained_set = set(retained_ids)
    reset_n = 0
    quarantine_n = 0
    for row in rows:
        rid = int(row["id"])
        bid = _norm_bag(row.get("bag_id"))
        if bid in retained_set:
            _reset_row_to_pending_wash(cursor, rid)
            reset_n += 1
        else:
            _quarantine_row(cursor, rid)
            quarantine_n += 1

    # Clear any prior manager-excluded rows from pre-cutover (quarantine, not delete).
    cursor.execute(
        """
        UPDATE hd_day_bag_production
        SET workflow_status = %s,
            version = version + 1
        WHERE organization_id = %s
          AND workflow_status = %s
        """,
        (WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED, org, STATUS_EXCLUDED),
    )

    after_day = build_rinse_hd_day(cursor, org, day, status="all")
    summary = after_day.get("summary") or {}
    audit = {
        "before": before_counts,
        "retained_pending_wash_ids": retained_ids,
        "quarantined": quarantine_n,
        "reset_pending": reset_n,
        "after_summary": summary,
    }
    cursor.execute(
        f"""
        UPDATE {_HD_SETTINGS_TABLE}
        SET fresh_start_audit_json = %s
        WHERE organization_id = %s
        """,
        (json.dumps(audit, default=str), org),
    )
    return {
        "ok": True,
        "fresh_start_at": fresh_naive.isoformat(sep=" "),
        "before": before_counts,
        "retained_pending_wash_ids": retained_ids,
        "after": {
            "pending_wash": int(summary.get("pending_wash") or 0),
            "awaiting_fold": int(summary.get("awaiting_fold") or summary.get("washed") or 0),
            "awaiting_entry": int(summary.get("awaiting_entry") or 0),
            "complete": int(summary.get("complete") or 0),
            "excluded": int((after_day.get("counts") or {}).get(STATUS_EXCLUDED) or 0),
        },
        "quarantined": quarantine_n,
        "reset_pending": reset_n,
    }


def _load_excluded_production_rows(cursor, organization_id: int) -> list[dict[str, Any]]:
    ensure_hd_exclude_columns(cursor)
    if not table_exists(cursor, "hd_day_bag_production"):
        return []
    cursor.execute(
        """
        SELECT *
        FROM hd_day_bag_production
        WHERE organization_id = %s AND workflow_status = %s
        ORDER BY excluded_at DESC, bag_id ASC
        """,
        (int(organization_id), STATUS_EXCLUDED),
    )
    return [dict(r) for r in (cursor.fetchall() or [])]


def build_excluded_hd_orders(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date | None = None,
) -> list[dict[str, Any]]:
    rows = _load_excluded_production_rows(cursor, organization_id)
    if not rows:
        return []
    org = int(organization_id)
    bag_ids = [_norm_bag(r.get("bag_id")) for r in rows if _norm_bag(r.get("bag_id"))]
    try:
        from backend.rinse_employee_productivity_sessions import resolve_customer_names_for_bags

        name_seed = [{"bag_id": bid} for bid in bag_ids]
        named = resolve_customer_names_for_bags(
            cursor, org, name_seed, selected_date_et=selected_date_et
        )
        name_map = {_norm_bag(n.get("bag_id")): n.get("customer_name") for n in named}
    except Exception:
        name_map = {}

    orders: list[dict[str, Any]] = []
    for row in rows:
        bid = _norm_bag(row.get("bag_id"))
        compact = _compact_order(
            {
                "bag_id": bid,
                "customer_name": name_map.get(bid),
                "status": STATUS_EXCLUDED,
                "washed_at": row.get("washed_at"),
                "washed_by_name": row.get("washed_by_name_snapshot"),
                "folded_at": row.get("folded_at"),
                "folded_by_name": row.get("folded_by_name_snapshot"),
                "items": row.get("total_items"),
                "revenue": row.get("revenue"),
                "operations_date_et": row.get("operations_date_et"),
                "production_version": row.get("version"),
            }
        )
        compact["excluded_at"] = row.get("excluded_at")
        compact["excluded_by_name"] = row.get("excluded_by_name")
        compact["excluded_reason"] = row.get("excluded_reason")
        compact["excluded_note"] = row.get("excluded_note")
        compact["excluded_from_status"] = row.get("excluded_from_status")
        compact["production_id"] = row.get("id")
        orders.append(compact)
    return attach_delivery_dates(cursor, org, orders)


def exclude_hd_order(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    reason: str | None = None,
    note: str | None = None,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    selected_date_et: date | None = None,
) -> dict[str, Any]:
    ensure_hd_exclude_columns(cursor)
    bid = _norm_bag(bag_id)
    org = int(organization_id)
    prod = _load_production_by_bag(cursor, org, [bid]).get(bid)
    if not prod:
        return {"ok": False, "error": "not_found"}
    wf = str(prod.get("workflow_status") or "").strip().lower()
    if wf == STATUS_EXCLUDED:
        return {"ok": True, "bag_id": bid, "already_excluded": True}
    if wf == WORKFLOW_STATUS_PRE_ACTIVATION_EXCLUDED.lower():
        return {"ok": False, "error": "pre_activation_quarantined"}

    day = selected_date_et or business_today()
    activation, fresh_at = hd_workflow_cutoff(cursor, org)
    events = _load_candidate_events_for_bags(cursor, org, day, [bid])
    state = resolve_order_state(
        events,
        service_hint="HD",
        production=prod,
        activation_date=activation,
        fresh_start_at=fresh_at,
    ) or {"status": wf or STATUS_PENDING_WASH}
    from_status = state.get("status") or wf or STATUS_PENDING_WASH
    now = business_now()
    now_naive = now.replace(tzinfo=None) if getattr(now, "tzinfo", None) else now
    cursor.execute(
        """
        UPDATE hd_day_bag_production SET
          workflow_status = %s,
          excluded_at = %s,
          excluded_by_user_id = %s,
          excluded_by_name = %s,
          excluded_reason = %s,
          excluded_note = %s,
          excluded_from_status = %s,
          updated_by_user_id = %s,
          version = version + 1
        WHERE id = %s
        """,
        (
            STATUS_EXCLUDED,
            now_naive,
            actor_user_id,
            actor_name,
            (reason or "manager_exclude")[:64],
            note,
            from_status,
            actor_user_id,
            int(prod["id"]),
        ),
    )
    return {"ok": True, "bag_id": bid, "excluded_from_status": from_status}


def restore_hd_order(
    cursor,
    organization_id: int,
    bag_id: str,
    *,
    actor_user_id: int | None = None,
    selected_date_et: date | None = None,
) -> dict[str, Any]:
    ensure_hd_exclude_columns(cursor)
    bid = _norm_bag(bag_id)
    org = int(organization_id)
    prod = _load_production_by_bag(cursor, org, [bid]).get(bid)
    if not prod:
        return {"ok": False, "error": "not_found"}
    if str(prod.get("workflow_status") or "").strip().lower() != STATUS_EXCLUDED:
        return {"ok": False, "error": "not_excluded"}

    activation, fresh_at = hd_workflow_cutoff(cursor, org)
    day = selected_date_et or business_today()
    events = _load_candidate_events_for_bags(cursor, org, day, [bid])
    user_maps = _load_user_maps(cursor, org)

    # Clear excluded marker and pre-cutover persisted wash/fold before re-derive.
    cursor.execute(
        """
        UPDATE hd_day_bag_production SET
          workflow_status = %s,
          washed_at = NULL,
          folded_at = NULL,
          washed_by_user_id = NULL,
          folded_by_user_id = NULL,
          washed_by_name_snapshot = NULL,
          folded_by_name_snapshot = NULL,
          washed_date_et = NULL,
          folded_date_et = NULL,
          washed_attribution_source = NULL,
          folded_attribution_source = NULL,
          management_completed_at = NULL,
          management_completed_by_user_id = NULL,
          management_completed_by_name = NULL,
          status = %s,
          excluded_at = NULL,
          excluded_by_user_id = NULL,
          excluded_by_name = NULL,
          excluded_reason = NULL,
          excluded_note = NULL,
          excluded_from_status = NULL,
          updated_by_user_id = %s,
          version = version + 1
        WHERE id = %s
        """,
        (STATUS_PENDING_WASH, PROD_NOT_RECORDED, actor_user_id, int(prod["id"])),
    )
    refreshed = _load_production_by_bag(cursor, org, [bid]).get(bid) or prod
    updated = _persist_scan_state_for_admitted(
        cursor,
        org=org,
        bid=bid,
        events=events,
        production=refreshed,
        user_maps=user_maps,
        activation=activation,
        fresh_start_at=fresh_at,
    )
    if updated:
        refreshed = updated
    state = resolve_order_state(
        events,
        service_hint="HD",
        production=refreshed,
        user_maps=user_maps,
        activation_date=activation,
        fresh_start_at=fresh_at,
    ) or {"status": STATUS_PENDING_WASH, "bag_id": bid}
    return {"ok": True, "bag_id": bid, "restored_status": state.get("status")}


def permanent_delete_hd_orders(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str],
    *,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    ensure_hd_exclude_columns(cursor)
    org = int(organization_id)
    ids = sorted({_norm_bag(b) for b in bag_ids if _norm_bag(b)})
    if not ids:
        return {"ok": False, "error": "no_bag_ids", "deleted": 0}
    ph = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT id, bag_id
        FROM hd_day_bag_production
        WHERE organization_id = %s
          AND bag_id IN ({ph})
          AND workflow_status = %s
        """,
        (org, *ids, STATUS_EXCLUDED),
    )
    rows = cursor.fetchall() or []
    if not rows:
        return {"ok": False, "error": "none_excluded", "deleted": 0}
    prod_ids = [int(r["id"]) for r in rows]
    deleted_bags = [_norm_bag(r.get("bag_id")) for r in rows]
    if table_exists(cursor, "hd_day_bag_production_audits") and prod_ids:
        audit_fk_col = (
            "production_fact_id"
            if table_has_column(cursor, "hd_day_bag_production_audits", "production_fact_id")
            else "production_id"
        )
        ph2 = ",".join(["%s"] * len(prod_ids))
        cursor.execute(
            f"""
            DELETE FROM hd_day_bag_production_audits
            WHERE {audit_fk_col} IN ({ph2})
            """,
            tuple(prod_ids),
        )
    ph3 = ",".join(["%s"] * len(prod_ids))
    cursor.execute(
        f"""
        DELETE FROM hd_day_bag_production
        WHERE organization_id = %s AND id IN ({ph3})
        """,
        (org, *prod_ids),
    )
    return {
        "ok": True,
        "deleted": len(prod_ids),
        "bag_ids": deleted_bags,
        "shared_scans_deleted": False,
    }
