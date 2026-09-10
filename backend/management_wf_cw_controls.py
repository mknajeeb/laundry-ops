"""Current Workload manager controls — soft manual review / exclude overlays.

Operational overrides are bag-scoped and do **not** mutate OI open membership,
scan evidence, registry completion, or selected-date day-bag admission formulas.

Day-bag ``move_to_review`` / ``exclude`` alone cannot represent open CW Pending
bags that lack a selected-date day_bag row. This module stores durable soft
overrides and overlays CW presentation + Manual Review membership.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.business_time import business_now
from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_veewash_workload import (
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
    REASON_MANAGER_SENT_FOR_REVIEW,
)
from backend.ta_helpers import table_exists

OVERRIDE_MANUAL_REVIEW = "manual_review"
OVERRIDE_EXCLUDE = "exclude"
CW_CONTROLS_TABLE = "rinse_wf_cw_manager_overrides"


def ensure_cw_manager_overrides_table(cursor) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CW_CONTROLS_TABLE} (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            bag_id VARCHAR(32) NOT NULL,
            override_type VARCHAR(32) NOT NULL,
            active TINYINT(1) NOT NULL DEFAULT 1,
            reason_code VARCHAR(64) NULL,
            reason_text VARCHAR(512) NOT NULL,
            actor_user_id INT NULL,
            actor_display_name VARCHAR(255) NULL,
            order_instance_id BIGINT NULL,
            created_at_et DATETIME NOT NULL,
            cleared_at_et DATETIME NULL,
            cleared_by_user_id INT NULL,
            cleared_by_display_name VARCHAR(255) NULL,
            clear_reason_text VARCHAR(512) NULL,
            UNIQUE KEY uq_cw_mgr_override_org_bag (organization_id, bag_id),
            INDEX idx_cw_mgr_override_org_active (organization_id, active, override_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    try:
        from backend.ta_helpers import invalidate_schema_cache

        invalidate_schema_cache()
    except Exception:
        pass


def _now_et_naive() -> datetime:
    now = business_now()
    if getattr(now, "tzinfo", None) is not None:
        return now.replace(tzinfo=None, microsecond=0)
    return now.replace(microsecond=0)


def _as_override_row(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    bid = normalize_bag_id(row.get("bag_id"))
    if not bid:
        return None
    otype = str(row.get("override_type") or "").strip().lower()
    if otype not in (OVERRIDE_MANUAL_REVIEW, OVERRIDE_EXCLUDE):
        return None
    active = bool(int(row.get("active") or 0))
    return {
        "bag_id": bid,
        "override_type": otype,
        "active": active,
        "reason_code": str(row.get("reason_code") or "").strip().upper() or None,
        "reason_text": str(row.get("reason_text") or "").strip() or None,
        "actor_user_id": row.get("actor_user_id"),
        "actor_display_name": (str(row.get("actor_display_name") or "").strip() or None),
        "order_instance_id": row.get("order_instance_id"),
        "created_at_et": row.get("created_at_et"),
        "cleared_at_et": row.get("cleared_at_et"),
        "cleared_by_user_id": row.get("cleared_by_user_id"),
        "cleared_by_display_name": (
            str(row.get("cleared_by_display_name") or "").strip() or None
        ),
        "clear_reason_text": str(row.get("clear_reason_text") or "").strip() or None,
    }


def bulk_load_active_cw_overrides(
    cursor,
    organization_id: int,
    bag_ids: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """One query: active CW overrides, optionally scoped to bag_ids."""
    if not table_exists(cursor, CW_CONTROLS_TABLE):
        return {}
    org = int(organization_id)
    ids = sorted({normalize_bag_id(b) for b in (bag_ids or []) if normalize_bag_id(b)})
    if bag_ids is not None and not ids:
        return {}
    if ids:
        ph = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT *
            FROM {CW_CONTROLS_TABLE}
            WHERE organization_id = %s
              AND active = 1
              AND bag_id IN ({ph})
            """,
            (org, *ids),
        )
    else:
        cursor.execute(
            f"""
            SELECT *
            FROM {CW_CONTROLS_TABLE}
            WHERE organization_id = %s
              AND active = 1
            """,
            (org,),
        )
    out: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall() or []:
        parsed = _as_override_row(row if isinstance(row, Mapping) else None)
        if parsed and parsed.get("active"):
            out[parsed["bag_id"]] = parsed
    return out


def public_cw_override_fields(override: Mapping[str, Any] | None) -> dict[str, Any]:
    ov = _as_override_row(override) if override else None
    if not ov or not ov.get("active"):
        return {
            "cw_override_type": None,
            "manual_review_active": False,
            "excluded_from_workload": False,
            "manual_review_reason": None,
            "manual_review_reason_code": None,
            "sent_by": None,
            "sent_at": None,
        }
    otype = ov["override_type"]
    is_manual = otype == OVERRIDE_MANUAL_REVIEW
    is_exclude = otype == OVERRIDE_EXCLUDE
    return {
        "cw_override_type": otype,
        "manual_review_active": is_manual,
        "excluded_from_workload": is_exclude,
        "manual_review_reason": ov.get("reason_text"),
        "manual_review_reason_code": ov.get("reason_code") or REASON_MANAGER_SENT_FOR_REVIEW,
        "sent_by": ov.get("actor_display_name"),
        "sent_at": ov.get("created_at_et"),
    }


def apply_cw_manager_overlay(
    workload: Mapping[str, Any],
    overrides: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Overlay Pending/Review/Exclude presentation without changing OI open set.

    Natural OI membership is preserved under ``oi_*`` keys for invariants/tests.
    """
    out = dict(workload or {})
    items_in = list(out.get("items") or [])
    natural_pending = frozenset(out.get("pending") or [])
    natural_review = frozenset(out.get("review") or [])
    natural_open = frozenset(out.get("open") or [])

    out["oi_pending"] = natural_pending
    out["oi_review"] = natural_review
    out["oi_open"] = natural_open
    out["oi_counts"] = {
        "pending": len(natural_pending),
        "review": len(natural_review),
        "open": len(natural_open),
    }

    excluded: set[str] = set()
    manual: set[str] = set()
    for bid, raw in (overrides or {}).items():
        ov = _as_override_row(raw)
        if not ov or not ov.get("active"):
            continue
        if ov["override_type"] == OVERRIDE_EXCLUDE:
            excluded.add(bid)
        elif ov["override_type"] == OVERRIDE_MANUAL_REVIEW:
            manual.add(bid)

    new_items: list[dict[str, Any]] = []
    for raw in items_in:
        item = dict(raw)
        bid = normalize_bag_id(item.get("bag_id"))
        if not bid:
            continue
        if bid in excluded:
            continue
        ov = _as_override_row(overrides.get(bid)) if bid in overrides else None
        system_codes = [
            str(c).strip().upper()
            for c in (item.get("review_reason_codes") or [])
            if str(c or "").strip()
        ]
        system_review = bid in natural_review or bool(system_codes)
        manual_review = bid in manual
        pub = public_cw_override_fields(ov if manual_review else None)

        if manual_review:
            if REASON_MANAGER_SENT_FOR_REVIEW not in system_codes:
                system_codes = [*system_codes, REASON_MANAGER_SENT_FOR_REVIEW]
            item["status"] = OUTCOME_REVIEW_REQUIRED
            item["review_reason_codes"] = system_codes
            item.update(pub)
            if system_review:
                item["review_origin"] = "both"
                item["system_review_reason_codes"] = [
                    c for c in system_codes if c != REASON_MANAGER_SENT_FOR_REVIEW
                ]
            else:
                item["review_origin"] = "manual"
                item["system_review_reason_codes"] = []
        elif system_review:
            item["status"] = OUTCOME_REVIEW_REQUIRED
            item["review_reason_codes"] = system_codes
            item["review_origin"] = "system"
            item["system_review_reason_codes"] = system_codes
            item.update(public_cw_override_fields(None))
        else:
            item["status"] = OUTCOME_PENDING
            item["review_reason_codes"] = []
            item["review_origin"] = None
            item["system_review_reason_codes"] = []
            item.update(public_cw_override_fields(None))
        new_items.append(item)

    review_bags = {
        normalize_bag_id(i.get("bag_id"))
        for i in new_items
        if str(i.get("status") or "").strip().lower() == OUTCOME_REVIEW_REQUIRED
    }
    review_bags.discard(None)
    pending_bags = {
        normalize_bag_id(i.get("bag_id"))
        for i in new_items
        if normalize_bag_id(i.get("bag_id")) and normalize_bag_id(i.get("bag_id")) not in review_bags
    }
    open_bags = frozenset(pending_bags | review_bags)

    out["items"] = new_items
    out["pending"] = frozenset(pending_bags)
    out["review"] = frozenset(review_bags)
    out["open"] = open_bags
    out["excluded_from_workload"] = frozenset(excluded & natural_open)
    out["counts"] = {
        "pending": len(pending_bags),
        "review": len(review_bags),
        "open": len(open_bags),
        "excluded": len(excluded & natural_open),
    }
    out["manager_overlay"] = {
        "source": "rinse_wf_cw_manager_overrides",
        "manual_review": sorted(manual & natural_open),
        "excluded": sorted(excluded & natural_open),
    }
    return out


def upsert_cw_override(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    override_type: str,
    reason_text: str,
    reason_code: str | None = None,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    order_instance_id: int | None = None,
) -> dict[str, Any]:
    ensure_cw_manager_overrides_table(cursor)
    bid = normalize_bag_id(bag_id)
    otype = str(override_type or "").strip().lower()
    reason = str(reason_text or "").strip()
    if not bid:
        return {"ok": False, "error": "invalid_bag_id"}
    if otype not in (OVERRIDE_MANUAL_REVIEW, OVERRIDE_EXCLUDE):
        return {"ok": False, "error": "invalid_override_type"}
    if not reason:
        return {"ok": False, "error": "reason_required"}

    code = (
        str(reason_code or "").strip().upper()
        or (
            REASON_MANAGER_SENT_FOR_REVIEW
            if otype == OVERRIDE_MANUAL_REVIEW
            else "MANAGER_EXCLUDED_FROM_WORKLOAD"
        )
    )
    at = _now_et_naive()
    by = (actor_display_name or "").strip() or None
    cursor.execute(
        f"""
        INSERT INTO {CW_CONTROLS_TABLE} (
            organization_id, bag_id, override_type, active,
            reason_code, reason_text, actor_user_id, actor_display_name,
            order_instance_id, created_at_et,
            cleared_at_et, cleared_by_user_id, cleared_by_display_name, clear_reason_text
        ) VALUES (
            %s,%s,%s,1,%s,%s,%s,%s,%s,%s,NULL,NULL,NULL,NULL
        )
        ON DUPLICATE KEY UPDATE
            override_type = VALUES(override_type),
            active = 1,
            reason_code = VALUES(reason_code),
            reason_text = VALUES(reason_text),
            actor_user_id = VALUES(actor_user_id),
            actor_display_name = VALUES(actor_display_name),
            order_instance_id = COALESCE(VALUES(order_instance_id), order_instance_id),
            created_at_et = VALUES(created_at_et),
            cleared_at_et = NULL,
            cleared_by_user_id = NULL,
            cleared_by_display_name = NULL,
            clear_reason_text = NULL
        """,
        (
            int(organization_id),
            bid,
            otype,
            code,
            reason[:512],
            actor_user_id,
            by,
            order_instance_id,
            at,
        ),
    )
    return {
        "ok": True,
        "bag_id": bid,
        "override_type": otype,
        "reason_code": code,
        "reason_text": reason,
        "actor_display_name": by,
        "created_at_et": at.isoformat(sep=" ", timespec="seconds"),
    }


def clear_cw_override(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    clear_reason_text: str | None = None,
    only_types: Sequence[str] | None = None,
) -> dict[str, Any]:
    ensure_cw_manager_overrides_table(cursor)
    bid = normalize_bag_id(bag_id)
    if not bid:
        return {"ok": False, "error": "invalid_bag_id"}
    at = _now_et_naive()
    by = (actor_display_name or "").strip() or None
    types = [
        str(t).strip().lower()
        for t in (only_types or [OVERRIDE_MANUAL_REVIEW, OVERRIDE_EXCLUDE])
        if str(t or "").strip()
    ]
    if not types:
        types = [OVERRIDE_MANUAL_REVIEW]
    ph = ",".join(["%s"] * len(types))
    cursor.execute(
        f"""
        UPDATE {CW_CONTROLS_TABLE}
        SET active = 0,
            cleared_at_et = %s,
            cleared_by_user_id = %s,
            cleared_by_display_name = %s,
            clear_reason_text = %s
        WHERE organization_id = %s
          AND bag_id = %s
          AND active = 1
          AND override_type IN ({ph})
        """,
        (
            at,
            actor_user_id,
            by,
            (str(clear_reason_text or "").strip() or None),
            int(organization_id),
            bid,
            *types,
        ),
    )
    return {
        "ok": True,
        "bag_id": bid,
        "cleared": int(getattr(cursor, "rowcount", 0) or 0) > 0,
        "cleared_at_et": at.isoformat(sep=" ", timespec="seconds"),
        "cleared_by": by,
    }


def move_pending_to_manual_review(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    reason_text: str,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    order_instance_id: int | None = None,
    selected_date_et=None,
) -> dict[str, Any]:
    """Soft-move open CW Pending bag into Manual Review (no scan/OI rewrite)."""
    from backend.rinse_veewash_step1_api import _record_correction

    out = upsert_cw_override(
        cursor,
        organization_id,
        bag_id=bag_id,
        override_type=OVERRIDE_MANUAL_REVIEW,
        reason_text=reason_text,
        reason_code=REASON_MANAGER_SENT_FOR_REVIEW,
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        order_instance_id=order_instance_id,
    )
    if not out.get("ok"):
        return out

    bid = out["bag_id"]
    _record_correction(
        cursor,
        organization_id,
        bag_id=bid,
        action="cw_move_to_review",
        reason_text=str(reason_text).strip(),
        reason_code=REASON_MANAGER_SENT_FOR_REVIEW,
        previous_values={"cw_status": "pending"},
        new_values={
            "cw_override_type": OVERRIDE_MANUAL_REVIEW,
            "reason_code": REASON_MANAGER_SENT_FOR_REVIEW,
            "selected_date_et": str(selected_date_et) if selected_date_et else None,
            "order_instance_id": order_instance_id,
        },
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
    )

    # Best-effort: if a selected-date day_bag exists, reuse stamp infrastructure.
    # Never invent day membership when the bag is absent from that day.
    day_sync = None
    if selected_date_et is not None:
        try:
            from backend.rinse_veewash_shift_day import load_day_bags_by_ids
            from backend.rinse_manual_review import stamp_manual_review_sent_back

            rows = load_day_bags_by_ids(
                cursor, organization_id, selected_date_et, [bid]
            )
            if rows:
                day_row = rows[0]
                snap = dict(day_row.get("bag_snapshot") or {})
                snap = stamp_manual_review_sent_back(
                    snap,
                    reason_codes=[REASON_MANAGER_SENT_FOR_REVIEW],
                    actor_user_id=actor_user_id,
                    actor_display_name=actor_display_name,
                )
                snap["cw_manual_review_reason"] = str(reason_text).strip()
                # Preserve existing system reasons; append manager-sent marker.
                reasons = [
                    str(c).strip().upper()
                    for c in (day_row.get("review_reason_codes") or [])
                    if str(c or "").strip()
                ]
                if REASON_MANAGER_SENT_FOR_REVIEW not in reasons:
                    reasons.append(REASON_MANAGER_SENT_FOR_REVIEW)
                cursor.execute(
                    """
                    UPDATE rinse_shift_monitor_day_bags
                    SET effective_status = %s,
                        review_reason_codes_json = %s,
                        bag_snapshot_json = %s,
                        manager_edit_version = manager_edit_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                    """,
                    (
                        OUTCOME_REVIEW_REQUIRED,
                        json.dumps(reasons),
                        json.dumps(snap, default=str),
                        int(organization_id),
                        selected_date_et,
                        bid,
                    ),
                )
                day_sync = {
                    "synced": True,
                    "effective_status": OUTCOME_REVIEW_REQUIRED,
                    "reason_codes": reasons,
                }
            else:
                day_sync = {"synced": False, "reason": "day_bag_absent"}
        except Exception as exc:
            day_sync = {"synced": False, "reason": "day_bag_sync_failed", "detail": str(exc)}

    try:
        from backend.rinse_veewash_step1_api import _clear_management_today_after_specialty_mutation
        from backend.business_time import business_today

        _clear_management_today_after_specialty_mutation(
            organization_id, selected_date_et or business_today()
        )
    except Exception:
        pass

    return {**out, "action": "move_to_review", "day_bag_sync": day_sync}


def exclude_from_current_workload(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    reason_text: str,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    order_instance_id: int | None = None,
    selected_date_et=None,
) -> dict[str, Any]:
    """Soft-exclude open CW bag from operational workload (no deletes / no OI close)."""
    from backend.rinse_veewash_step1_api import _record_correction

    # Step1 outcome=exclude only patches day_bags and does not remove open CW
    # bags from OI membership — so CW soft-exclude lives here instead.
    out = upsert_cw_override(
        cursor,
        organization_id,
        bag_id=bag_id,
        override_type=OVERRIDE_EXCLUDE,
        reason_text=reason_text,
        reason_code="MANAGER_EXCLUDED_FROM_WORKLOAD",
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        order_instance_id=order_instance_id,
    )
    if not out.get("ok"):
        return out

    bid = out["bag_id"]
    _record_correction(
        cursor,
        organization_id,
        bag_id=bid,
        action="cw_exclude",
        reason_text=str(reason_text).strip(),
        reason_code="MANAGER_EXCLUDED_FROM_WORKLOAD",
        previous_values={"cw_status": "open"},
        new_values={
            "cw_override_type": OVERRIDE_EXCLUDE,
            "selected_date_et": str(selected_date_et) if selected_date_et else None,
            "order_instance_id": order_instance_id,
        },
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
    )

    day_sync = None
    if selected_date_et is not None:
        try:
            from backend.rinse_veewash_shift_day import load_day_bags_by_ids

            rows = load_day_bags_by_ids(
                cursor, organization_id, selected_date_et, [bid]
            )
            if rows:
                day_row = rows[0]
                snap = dict(day_row.get("bag_snapshot") or {})
                snap["cw_operational_exclude"] = {
                    "active": True,
                    "reason": str(reason_text).strip(),
                    "by": (actor_display_name or "").strip() or None,
                    "actor_user_id": actor_user_id,
                    "at": out.get("created_at_et"),
                }
                cursor.execute(
                    """
                    UPDATE rinse_shift_monitor_day_bags
                    SET effective_status = 'excluded',
                        disposition = 'EXCLUDE',
                        bag_snapshot_json = %s,
                        manager_edit_version = manager_edit_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                    """,
                    (
                        json.dumps(snap, default=str),
                        int(organization_id),
                        selected_date_et,
                        bid,
                    ),
                )
                day_sync = {"synced": True, "effective_status": "excluded"}
            else:
                day_sync = {"synced": False, "reason": "day_bag_absent"}
        except Exception as exc:
            day_sync = {"synced": False, "reason": "day_bag_sync_failed", "detail": str(exc)}

    try:
        from backend.rinse_veewash_step1_api import _clear_management_today_after_specialty_mutation
        from backend.business_time import business_today

        _clear_management_today_after_specialty_mutation(
            organization_id, selected_date_et or business_today()
        )
    except Exception:
        pass

    return {**out, "action": "exclude", "day_bag_sync": day_sync}


def resolve_manual_cw_review(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
    clear_reason_text: str | None = None,
    selected_date_et=None,
) -> dict[str, Any]:
    """Clear Manual Review override only — system review reasons remain."""
    from backend.rinse_veewash_step1_api import _record_correction

    before = bulk_load_active_cw_overrides(cursor, organization_id, [bag_id]).get(
        normalize_bag_id(bag_id) or ""
    )
    out = clear_cw_override(
        cursor,
        organization_id,
        bag_id=bag_id,
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        clear_reason_text=clear_reason_text or "Resolved manual review",
        only_types=[OVERRIDE_MANUAL_REVIEW],
    )
    if not out.get("ok"):
        return out

    bid = out["bag_id"]
    _record_correction(
        cursor,
        organization_id,
        bag_id=bid,
        action="cw_resolve_manual_review",
        reason_text=str(clear_reason_text or "Resolved manual review").strip(),
        reason_code="MANUAL_REVIEW_RESOLVED",
        previous_values={"override": before},
        new_values={"manual_review_active": False},
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
    )

    # If day_bag only had manager-sent (no other system codes), clear it back to pending.
    if selected_date_et is not None:
        try:
            from backend.rinse_veewash_shift_day import load_day_bags_by_ids
            from backend.rinse_manual_review import stamp_manual_review_resolved

            rows = load_day_bags_by_ids(
                cursor, organization_id, selected_date_et, [bid]
            )
            if rows:
                day_row = rows[0]
                reasons = [
                    str(c).strip().upper()
                    for c in (day_row.get("review_reason_codes") or [])
                    if str(c or "").strip()
                ]
                remaining = [c for c in reasons if c != REASON_MANAGER_SENT_FOR_REVIEW]
                snap = dict(day_row.get("bag_snapshot") or {})
                snap = stamp_manual_review_resolved(
                    snap,
                    prior_reason_codes=reasons or [REASON_MANAGER_SENT_FOR_REVIEW],
                    actor_user_id=actor_user_id,
                    actor_display_name=actor_display_name,
                )
                snap.pop("cw_manual_review_reason", None)
                new_status = (
                    OUTCOME_REVIEW_REQUIRED if remaining else OUTCOME_PENDING
                )
                cursor.execute(
                    """
                    UPDATE rinse_shift_monitor_day_bags
                    SET effective_status = %s,
                        review_reason_codes_json = %s,
                        bag_snapshot_json = %s,
                        manager_edit_version = manager_edit_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE organization_id = %s AND shift_date_et = %s AND bag_id = %s
                    """,
                    (
                        new_status,
                        json.dumps(remaining),
                        json.dumps(snap, default=str),
                        int(organization_id),
                        selected_date_et,
                        bid,
                    ),
                )
                out["day_bag_sync"] = {
                    "synced": True,
                    "effective_status": new_status,
                    "remaining_reason_codes": remaining,
                }
        except Exception as exc:
            out["day_bag_sync"] = {
                "synced": False,
                "reason": "day_bag_sync_failed",
                "detail": str(exc),
            }

    try:
        from backend.rinse_veewash_step1_api import _clear_management_today_after_specialty_mutation
        from backend.business_time import business_today

        _clear_management_today_after_specialty_mutation(
            organization_id, selected_date_et or business_today()
        )
    except Exception:
        pass

    return {**out, "action": "resolve_manual_review"}
