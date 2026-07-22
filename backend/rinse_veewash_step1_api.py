"""Step-1 drill-down + manager correction actions for Review Required."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from backend.rinse_bag_completion import normalize_bag_id
from backend.rinse_operator_manual_correction import (
    apply_operator_approved_manual_completion,
    write_operator_audit_log,
)
from backend.rinse_processing_settings import DEFAULT_FACILITY_ENTRY_RACKS
from backend.rinse_veewash_workload import (
    SERVICE_HD,
    SERVICE_WF,
    VEEWASH_ORG_ID,
    build_step1_headline_summary,
    build_veewash_daily_workload,
    get_step1_activation_date,
    today_et,
)
from backend.ta_helpers import table_exists


def ensure_step1_correction_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_step1_corrections (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            organization_id INT NOT NULL,
            bag_id VARCHAR(32) NOT NULL,
            action VARCHAR(64) NOT NULL,
            reason_code VARCHAR(64) NULL,
            reason_text VARCHAR(512) NOT NULL,
            previous_values JSON NULL,
            new_values JSON NULL,
            actor_user_id INT NULL,
            actor_display_name VARCHAR(255) NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_step1_corr_org_bag (organization_id, bag_id),
            INDEX idx_step1_corr_created (organization_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw
    text = str(raw).strip().replace("Z", "")
    try:
        if "T" in text:
            return datetime.fromisoformat(text)
        if " " in text:
            return datetime.fromisoformat(text.replace(" ", "T", 1))
        d = date.fromisoformat(text[:10])
        return datetime(d.year, d.month, d.day, 12, 0, 0)
    except ValueError:
        return None


def _record_correction(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    action: str,
    reason_text: str,
    reason_code: str | None,
    previous_values: dict | None,
    new_values: dict | None,
    actor_user_id: int | None,
    actor_display_name: str | None,
) -> None:
    ensure_step1_correction_table(cursor)
    cursor.execute(
        """
        INSERT INTO rinse_step1_corrections (
            organization_id, bag_id, action, reason_code, reason_text,
            previous_values, new_values, actor_user_id, actor_display_name
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            normalize_bag_id(bag_id),
            action,
            reason_code,
            reason_text,
            json.dumps(previous_values, default=str) if previous_values else None,
            json.dumps(new_values, default=str) if new_values else None,
            actor_user_id,
            actor_display_name,
        ),
    )
    write_operator_audit_log(
        cursor,
        organization_id,
        bag_id=bag_id,
        action=f"step1_{action}",
        old_value=previous_values,
        new_value=new_values,
        remarks=reason_text,
        actor_user_id=actor_user_id,
    )


def build_step1_payload(cursor, organization_id: int, selected_date_et: date) -> dict[str, Any]:
    wl = build_veewash_daily_workload(
        cursor, organization_id, selected_date_et=selected_date_et
    )
    activation = get_step1_activation_date(cursor, organization_id) or selected_date_et
    summary = build_step1_headline_summary(
        wl, selected_date_et=selected_date_et, activation_date=activation
    )
    return {"workload": wl, "summary": summary}


def _filter_bag_ids(
    summary: dict[str, Any],
    *,
    metric: str,
    service: str,
    rush: str,
) -> list[str]:
    from backend.rinse_veewash_workload import _rush_bucket

    segs = summary.get("segments") or {}
    # Resolve segment key
    svc = (service or "all").lower()
    r = (rush or "all").lower().replace("-", "_")
    if svc == "wf" and r == "rush":
        key = "wf_rush"
    elif svc == "wf" and r == "non_rush":
        key = "wf_non_rush"
    elif svc == "hd" and r == "rush":
        key = "hd_rush"
    elif svc == "hd" and r == "non_rush":
        key = "hd_non_rush"
    elif svc == "wf":
        key = "wf"
    elif svc == "hd":
        key = "hd"
    elif r == "rush":
        key = "rush"
    elif r == "non_rush":
        key = "non_rush"
    else:
        key = "all"

    seg = segs.get(key) or segs.get("all") or {}
    bags = seg.get("bag_ids") or {}
    metric_key = {
        "new_today": "new_today",
        "carryover": "carryover",
        "completed": "completed",
        "pending": "pending",
        "review_required": "review_required",
        "active_workload": None,
        "washed": "completed",  # HD stage alias until separate stage model
        "folded": "completed",
    }.get(metric, metric)

    if metric_key is None:
        ids = list(bags.get("new_today") or []) + list(bags.get("carryover") or [])
    else:
        ids = list(bags.get(metric_key) or [])
    return sorted(set(ids))


def load_scans_for_bags(
    cursor, organization_id: int, bag_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    if not bag_ids or not table_exists(cursor, "rinse_bag_scan_events"):
        return {}
    placeholders = ",".join(["%s"] * len(bag_ids))
    cursor.execute(
        f"""
        SELECT bag_id, scanned_at_parsed, purpose, rack, user_name, weight_lbs
        FROM rinse_bag_scan_events
        WHERE organization_id = %s AND bag_id IN ({placeholders})
        ORDER BY scanned_at_parsed ASC, id ASC
        """,
        (int(organization_id), *bag_ids),
    )
    out: dict[str, list[dict[str, Any]]] = {b: [] for b in bag_ids}
    for row in cursor.fetchall() or []:
        bid = normalize_bag_id(row.get("bag_id"))
        if bid in out:
            out[bid].append(
                {
                    "scanned_at_parsed": row.get("scanned_at_parsed"),
                    "purpose": row.get("purpose"),
                    "rack": row.get("rack"),
                    "user_name": row.get("user_name"),
                    "weight_lbs": float(row["weight_lbs"])
                    if row.get("weight_lbs") is not None
                    else None,
                }
            )
    return out


def build_drilldown(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    metric: str,
    service: str = "all",
    rush: str = "all",
) -> dict[str, Any]:
    payload = build_step1_payload(cursor, organization_id, selected_date_et)
    wl = payload["workload"]
    summary = payload["summary"]
    ids = _filter_bag_ids(summary, metric=metric, service=service, rush=rush)
    rows_by_id = {r.get("bag_id"): r for r in (wl.get("rows") or []) if r.get("bag_id")}
    reasons = wl.get("review_reasons_by_bag") or summary.get("review_reasons_by_bag") or {}
    scans = load_scans_for_bags(cursor, organization_id, ids)

    # Latest corrections per bag
    corrections: dict[str, list] = {b: [] for b in ids}
    if ids and table_exists(cursor, "rinse_step1_corrections"):
        placeholders = ",".join(["%s"] * len(ids))
        cursor.execute(
            f"""
            SELECT bag_id, action, reason_code, reason_text, previous_values, new_values,
                   actor_display_name, created_at
            FROM rinse_step1_corrections
            WHERE organization_id = %s AND bag_id IN ({placeholders})
            ORDER BY created_at DESC
            """,
            (int(organization_id), *ids),
        )
        for row in cursor.fetchall() or []:
            bid = normalize_bag_id(row.get("bag_id"))
            if bid in corrections:
                corrections[bid].append(
                    {
                        "action": row.get("action"),
                        "reason_code": row.get("reason_code"),
                        "reason_text": row.get("reason_text"),
                        "previous_values": row.get("previous_values"),
                        "new_values": row.get("new_values"),
                        "actor_display_name": row.get("actor_display_name"),
                        "created_at": row.get("created_at"),
                    }
                )

    bags = []
    for bid in ids:
        r = rows_by_id.get(bid) or {}
        bags.append(
            {
                "bag_id": bid,
                "customer_name": r.get("customer_name"),
                "service_type": r.get("service_type"),
                "rush_flag": r.get("rush_flag"),
                "entry_class": r.get("entry_class"),
                "dashboard_status": r.get("outcome") or r.get("final_bucket"),
                "canonical_status": r.get("canonical_status"),
                "reason_codes": list(reasons.get(bid) or r.get("reason_codes") or []),
                "weight_lbs": r.get("weight_lbs"),
                "entry_at": r.get("original_entry_date"),
                "entry_source": r.get("entry_source"),
                "completion_at": r.get("completion_at"),
                "completed_by": r.get("completed_by"),
                "portal_status": r.get("portal_status"),
                "last_seen_at": r.get("last_seen_date"),
                "scans": scans.get(bid) or [],
                "corrections": corrections.get(bid) or [],
                "system_result": {
                    "outcome": r.get("outcome"),
                    "canonical_status": r.get("canonical_status"),
                    "reason_codes": list(reasons.get(bid) or r.get("reason_codes") or []),
                    "completion_at": r.get("completion_at"),
                    "completed_by": r.get("completed_by"),
                },
            }
        )
    return {
        "selected_date_et": selected_date_et.isoformat(),
        "metric": metric,
        "service": service,
        "rush": rush,
        "bags": bags,
        "review_by_reason": summary.get("review_by_reason") or {},
    }


def apply_step1_correction(
    cursor,
    organization_id: int,
    *,
    bag_id: str,
    action: str,
    body: dict[str, Any],
    actor_user_id: int | None = None,
    actor_display_name: str | None = None,
) -> dict[str, Any]:
    bid = normalize_bag_id(bag_id)
    action = str(action or "").strip().lower()
    reason = str(body.get("reason") or body.get("correction_reason") or "").strip()
    if not bid:
        return {"ok": False, "error": "invalid_bag_id"}
    if not reason:
        return {"ok": False, "error": "reason_required"}

    day_raw = body.get("selected_date_et") or body.get("date")
    day = today_et()
    if day_raw:
        try:
            day = date.fromisoformat(str(day_raw)[:10])
        except ValueError:
            pass

    # Snapshot prior row from workload
    payload = build_step1_payload(cursor, organization_id, day)
    prior = next(
        (r for r in (payload["workload"].get("rows") or []) if r.get("bag_id") == bid),
        {},
    )

    if action in ("mark_completed", "correct_completion"):
        emp = str(body.get("employee") or body.get("completed_by") or "").strip()
        ts = _parse_dt(body.get("completion_at") or body.get("completion_timestamp"))
        if not emp or not ts:
            return {"ok": False, "error": "employee_and_completion_at_required"}
        weight = body.get("weight_lbs")
        try:
            weight_f = float(weight) if weight not in (None, "") else 0.1
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_weight"}
        # Need an upload batch id — use 0 sentinel if helper requires int
        out = apply_operator_approved_manual_completion(
            cursor,
            organization_id,
            bid,
            credited_employee=emp,
            weight_lbs=weight_f,
            selected_date_et=day,
            completion_timestamp=ts,
            upload_batch_id=int(body.get("upload_batch_id") or 0),
            remarks=reason,
            actor_user_id=actor_user_id,
        )
        _record_correction(
            cursor,
            organization_id,
            bag_id=bid,
            action=action,
            reason_text=reason,
            reason_code=str(body.get("reason_code") or "MANUAL_COMPLETION"),
            previous_values=prior,
            new_values={"completion_at": ts.isoformat(), "employee": emp, "result": out},
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
        return {"ok": True, "action": action, "result": out}

    if action == "correct_weight":
        try:
            weight_f = float(body.get("weight_lbs"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "weight_lbs_required"}
        if weight_f <= 0:
            return {"ok": False, "error": "weight_must_be_positive"}
        emp = str(body.get("employee") or "manager").strip()
        ts = _parse_dt(body.get("weight_at") or body.get("completion_at")) or datetime.utcnow()
        from backend.rinse_bag_registry import ensure_rinse_bag_scan_events_table
        from backend.rinse_scan_event_identity import dedupe_key_from_row
        from backend.rinse_workload_bag_weight import ensure_scan_events_weight_lbs_column

        ensure_rinse_bag_scan_events_table(cursor)
        ensure_scan_events_weight_lbs_column(cursor)
        time_raw = ts.strftime("%Y-%m-%d %H:%M:%S")
        row = {
            "organization_id": int(organization_id),
            "bag_id": bid,
            "purpose": "weight-entry",
            "scanned_at_parsed": ts,
            "time_scanned_raw": time_raw,
            "user_name": emp,
            "rack": None,
        }
        dedupe = dedupe_key_from_row(row)
        cursor.execute(
            """
            INSERT INTO rinse_bag_scan_events (
                organization_id, bag_id, purpose, scanned_at_parsed, time_scanned_raw,
                user_name, rack, weight_lbs, dedupe_key, raw_json
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE weight_lbs=VALUES(weight_lbs), user_name=VALUES(user_name)
            """,
            (
                int(organization_id),
                bid,
                "weight-entry",
                ts,
                time_raw,
                emp,
                None,
                weight_f,
                dedupe,
                json.dumps(
                    {
                        "backfill_source": "step1_correct_weight",
                        "Weight": weight_f,
                        "operator_approved": True,
                    }
                ),
            ),
        )
        _record_correction(
            cursor,
            organization_id,
            bag_id=bid,
            action=action,
            reason_text=reason,
            reason_code="WF_ZERO_OR_MISSING_WEIGHT",
            previous_values={"weight_lbs": prior.get("weight_lbs")},
            new_values={"weight_lbs": weight_f, "weight_at": ts.isoformat(), "employee": emp},
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
        return {"ok": True, "action": action, "weight_lbs": weight_f}

    if action == "correct_entry":
        svc = str(body.get("service_type") or prior.get("service_type") or SERVICE_WF).upper()
        ts = _parse_dt(body.get("entry_at") or body.get("entry_timestamp"))
        if not ts:
            return {"ok": False, "error": "entry_at_required"}
        if svc == SERVICE_HD:
            purpose = "workitems-added"
            rack = None
        else:
            purpose = "move-bag"
            rack = str(body.get("rack") or (DEFAULT_FACILITY_ENTRY_RACKS[0] if DEFAULT_FACILITY_ENTRY_RACKS else "VeeWash Dirty"))
        from backend.rinse_bag_registry import ensure_rinse_bag_scan_events_table
        from backend.rinse_scan_event_identity import dedupe_key_from_row

        ensure_rinse_bag_scan_events_table(cursor)
        time_raw = ts.strftime("%Y-%m-%d %H:%M:%S")
        emp = str(body.get("employee") or actor_display_name or "manager").strip()
        row = {
            "organization_id": int(organization_id),
            "bag_id": bid,
            "purpose": purpose,
            "scanned_at_parsed": ts,
            "time_scanned_raw": time_raw,
            "user_name": emp,
            "rack": rack,
        }
        dedupe = dedupe_key_from_row(row)
        cursor.execute(
            """
            INSERT INTO rinse_bag_scan_events (
                organization_id, bag_id, purpose, scanned_at_parsed, time_scanned_raw,
                user_name, rack, dedupe_key, raw_json
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE scanned_at_parsed=VALUES(scanned_at_parsed),
                rack=VALUES(rack), purpose=VALUES(purpose)
            """,
            (
                int(organization_id),
                bid,
                purpose,
                ts,
                time_raw,
                emp,
                rack,
                dedupe,
                json.dumps(
                    {
                        "backfill_source": "step1_correct_entry",
                        "service_type": svc,
                        "operator_approved": True,
                    }
                ),
            ),
        )
        _record_correction(
            cursor,
            organization_id,
            bag_id=bid,
            action=action,
            reason_text=reason,
            reason_code="COMPLETED_WITHOUT_RECOGNIZED_ENTRY",
            previous_values={"entry": prior.get("original_entry_date"), "service": prior.get("service_type")},
            new_values={
                "service_type": svc,
                "entry_at": ts.isoformat(),
                "purpose": purpose,
                "rack": rack,
            },
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
        return {"ok": True, "action": action, "entry_at": ts.isoformat(), "service_type": svc}

    if action in ("return_pending", "exclude"):
        _record_correction(
            cursor,
            organization_id,
            bag_id=bid,
            action=action,
            reason_text=reason,
            reason_code=str(body.get("reason_code") or action.upper()),
            previous_values=prior,
            new_values={"status": action},
            actor_user_id=actor_user_id,
            actor_display_name=actor_display_name,
        )
        # Soft flag via correction table; reporting prefers corrections on next expand.
        return {"ok": True, "action": action, "note": "audit_recorded"}

    return {"ok": False, "error": f"unknown_action:{action}"}
