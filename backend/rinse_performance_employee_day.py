"""Employee-day Performance aggregation and day-level overrides.

Invariant: one employee + one America/New_York calendar day = one Performance
result. Performance eligibility is APPROVED ∩ non-excluded sessions only.
Pending / Needs Approval / Disapproved sessions remain visible in Review but
contribute zero until approved. Excluded sessions are neither active-visible
nor eligible. Daily rate is always Σ approved pounds / Σ approved Folder hours
— never an average of session rates.

Day Average Weight (lb/bag) is applied once:

    effective_pounds = average_weight × approved_bag_count

Do not apply the same average independently to every session.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from backend.management_wf_folder_performance import weighted_aggregate_rates
from backend.rinse_performance_approvals import ROLE_FOLDER
from backend.ta_helpers import table_exists

DAY_OVERRIDES_TABLE = "rinse_performance_employee_day_overrides"
DAY_OVERRIDE_EVENTS_TABLE = "rinse_performance_employee_day_override_events"

# Authoritative Performance eligibility: APPROVED and non-excluded sessions only.
# Visibility of pending sessions is separate (see session_is_visible_non_excluded).
DASHBOARD_ELIGIBILITY = "approved_non_excluded"

_SCHEMA_READY = False


def session_is_excluded(session: Mapping[str, Any] | None) -> bool:
    if not session:
        return False
    status = str(
        session.get("publication_status")
        or (session.get("publication") or {}).get("status")
        or ""
    ).upper()
    if status == "EXCLUDED":
        return True
    pub = session.get("publication") or {}
    if pub.get("excluded") is True:
        return True
    if pub.get("excluded_at"):
        return True
    return False


def session_publication_status(session: Mapping[str, Any] | None) -> str:
    if not session:
        return ""
    return str(
        session.get("publication_status")
        or (session.get("publication") or {}).get("status")
        or ""
    ).upper()


def session_is_approved_for_metrics(session: Mapping[str, Any] | None) -> bool:
    """True when publication stamp is APPROVED (and not excluded)."""
    if not session or session_is_excluded(session):
        return False
    return session_publication_status(session) == "APPROVED"


def session_is_included_for_metrics(session: Mapping[str, Any] | None) -> bool:
    """Countable toward employee-day Performance bags/lbs/hours/rates.

    Visibility ≠ eligibility: non-excluded sessions remain visible in Review, but
    only APPROVED (and non-excluded) sessions contribute to Performance metrics.
    Pending / Needs Approval / Disapproved sessions contribute zero until approved.
    """
    if not session:
        return False
    if session_is_excluded(session):
        return False
    if not session.get("include_in_authoritative_aggregate", True):
        return False
    if not session_is_approved_for_metrics(session):
        return False
    status = str(session.get("role_status") or "").lower()
    if status == "unresolved":
        return False
    return True


def session_is_visible_non_excluded(session: Mapping[str, Any] | None) -> bool:
    """Operational visibility in Review (not Performance eligibility)."""
    if not session:
        return False
    if session_is_excluded(session):
        return False
    if not session.get("include_in_authoritative_aggregate", True):
        return False
    status = str(session.get("role_status") or "").lower()
    if status == "unresolved":
        return False
    return True


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    raw = str(value).strip().replace("Z", "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:26])
    except ValueError:
        return None


def _fmt_duration_hours(hours: float | None) -> str | None:
    if hours is None:
        return None
    h = float(hours)
    if h < 0:
        h = 0.0
    total_min = int(round(h * 60))
    hh, mm = divmod(total_min, 60)
    if hh and mm:
        return f"{hh}h {mm}m"
    if hh:
        return f"{hh}h"
    return f"{mm}m"


def employee_day_override_key(
    *,
    employee_user_id: int | None,
    employee_name: str,
) -> str:
    """Stable unique identity for a day override within org/role/date.

    Prefer numeric user id so two people with the same display name cannot collide.
    Name fallback is only for rare rows without user_id.
    """
    if employee_user_id is not None:
        return f"u:{int(employee_user_id)}"
    name = str(employee_name or "").strip().casefold()
    if not name:
        raise ValueError("employee_user_id or employee_name is required")
    return f"n:{name}"


def ensure_employee_day_override_tables(cursor) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    if not table_exists(cursor, DAY_OVERRIDES_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {DAY_OVERRIDES_TABLE} (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              role_key VARCHAR(32) NOT NULL,
              business_date_et DATE NOT NULL,
              employee_key VARCHAR(96) NOT NULL,
              employee_user_id INT NULL,
              employee_name VARCHAR(255) NOT NULL,
              average_weight_lbs DECIMAL(10,4) NULL,
              reason VARCHAR(255) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by INT NULL,
              updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
              updated_by INT NULL,
              UNIQUE KEY uq_rinse_perf_day_ov
                (organization_id, role_key, business_date_et, employee_key),
              KEY idx_rinse_perf_day_ov_emp
                (organization_id, role_key, business_date_et, employee_user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    else:
        # Additive migration if an older preview table lacked employee_key.
        cursor.execute(f"SHOW COLUMNS FROM {DAY_OVERRIDES_TABLE}")
        cols = {
            (r["Field"] if isinstance(r, dict) else r[0])
            for r in (cursor.fetchall() or [])
        }
        if "employee_key" not in cols:
            cursor.execute(
                f"""
                ALTER TABLE {DAY_OVERRIDES_TABLE}
                  ADD COLUMN employee_key VARCHAR(96) NULL AFTER business_date_et
                """
            )
            cursor.execute(
                f"""
                UPDATE {DAY_OVERRIDES_TABLE}
                SET employee_key = CASE
                  WHEN employee_user_id IS NOT NULL THEN CONCAT('u:', employee_user_id)
                  ELSE CONCAT('n:', LOWER(TRIM(employee_name)))
                END
                WHERE employee_key IS NULL OR employee_key=''
                """
            )
            cursor.execute(
                f"""
                ALTER TABLE {DAY_OVERRIDES_TABLE}
                  MODIFY COLUMN employee_key VARCHAR(96) NOT NULL
                """
            )
            try:
                cursor.execute(
                    f"ALTER TABLE {DAY_OVERRIDES_TABLE} DROP INDEX uq_rinse_perf_day_ov"
                )
            except Exception:
                pass
            cursor.execute(
                f"""
                ALTER TABLE {DAY_OVERRIDES_TABLE}
                  ADD UNIQUE KEY uq_rinse_perf_day_ov
                    (organization_id, role_key, business_date_et, employee_key)
                """
            )
    if not table_exists(cursor, DAY_OVERRIDE_EVENTS_TABLE):
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {DAY_OVERRIDE_EVENTS_TABLE} (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              organization_id INT NOT NULL,
              role_key VARCHAR(32) NOT NULL,
              business_date_et DATE NOT NULL,
              employee_key VARCHAR(96) NULL,
              employee_user_id INT NULL,
              employee_name VARCHAR(255) NOT NULL,
              action VARCHAR(32) NOT NULL,
              average_weight_lbs DECIMAL(10,4) NULL,
              end_time_et VARCHAR(64) NULL,
              target_session_id VARCHAR(64) NULL,
              target_segment_id INT NULL,
              actor_user_id INT NULL,
              actor_name VARCHAR(255) NULL,
              reason VARCHAR(255) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              KEY idx_rinse_perf_day_ov_ev
                (organization_id, role_key, business_date_et, employee_key)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    _SCHEMA_READY = True


def load_day_average_weight_overrides(
    cursor,
    organization_id: int,
    *,
    role_key: str,
    business_date_et: date,
) -> dict[str, float]:
    """Map employee_key → average_weight_lbs for the day (FOLDER role_key scoped)."""
    ensure_employee_day_override_tables(cursor)
    cursor.execute(
        f"""
        SELECT employee_key, employee_name, employee_user_id, average_weight_lbs
        FROM {DAY_OVERRIDES_TABLE}
        WHERE organization_id=%s AND role_key=%s AND business_date_et=%s
          AND average_weight_lbs IS NOT NULL
        """,
        (int(organization_id), str(role_key).upper(), business_date_et),
    )
    out: dict[str, float] = {}
    for row in cursor.fetchall() or []:
        r = dict(row) if not isinstance(row, dict) else row
        key = str(r.get("employee_key") or "").strip()
        if not key:
            try:
                key = employee_day_override_key(
                    employee_user_id=r.get("employee_user_id"),
                    employee_name=str(r.get("employee_name") or ""),
                )
            except ValueError:
                continue
        try:
            out[key] = float(r["average_weight_lbs"])
        except (TypeError, ValueError):
            continue
    return out


def upsert_day_average_weight(
    cursor,
    organization_id: int,
    *,
    role_key: str,
    business_date_et: date,
    employee_name: str,
    employee_user_id: int | None,
    average_weight_lbs: float | None,
    reason: str | None = None,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    """Set or clear day-level average bag weight (lb/bag). None clears."""
    ensure_employee_day_override_tables(cursor)
    org = int(organization_id)
    rk = str(role_key).upper()
    name = str(employee_name or "").strip()
    if not name and employee_user_id is None:
        return {"ok": False, "status": "missing_employee"}
    try:
        emp_key = employee_day_override_key(
            employee_user_id=employee_user_id,
            employee_name=name or f"user-{employee_user_id}",
        )
    except ValueError:
        return {"ok": False, "status": "missing_employee"}
    if average_weight_lbs is not None:
        w = float(average_weight_lbs)
        if w < 0:
            return {"ok": False, "status": "invalid_average_weight"}
    else:
        w = None

    cursor.execute(
        f"""
        INSERT INTO {DAY_OVERRIDES_TABLE} (
          organization_id, role_key, business_date_et, employee_key,
          employee_user_id, employee_name, average_weight_lbs, reason,
          created_by, updated_by
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          employee_user_id=VALUES(employee_user_id),
          employee_name=VALUES(employee_name),
          average_weight_lbs=VALUES(average_weight_lbs),
          reason=VALUES(reason),
          updated_by=VALUES(updated_by),
          updated_at=CURRENT_TIMESTAMP
        """,
        (
            org,
            rk,
            business_date_et,
            emp_key,
            int(employee_user_id) if employee_user_id is not None else None,
            name or emp_key,
            w,
            (reason or None) and str(reason)[:255],
            actor_user_id,
            actor_user_id,
        ),
    )
    action = "SET_AVERAGE_WEIGHT" if w is not None else "CLEAR_AVERAGE_WEIGHT"
    cursor.execute(
        f"""
        INSERT INTO {DAY_OVERRIDE_EVENTS_TABLE} (
          organization_id, role_key, business_date_et, employee_key,
          employee_user_id, employee_name, action, average_weight_lbs,
          actor_user_id, actor_name, reason
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            org,
            rk,
            business_date_et,
            emp_key,
            int(employee_user_id) if employee_user_id is not None else None,
            name or emp_key,
            action,
            w,
            actor_user_id,
            actor_name,
            (reason or None) and str(reason)[:255],
        ),
    )
    return {
        "ok": True,
        "action": action,
        "employee": name or emp_key,
        "employee_key": emp_key,
        "average_weight_lbs": w,
        "business_date_et": business_date_et.isoformat(),
        "role_key": rk,
    }


def recompute_employee_day_metrics(
    emp: dict[str, Any],
    *,
    average_weight_override: float | None = None,
) -> dict[str, Any]:
    """Rewrite employee card Performance totals from APPROVED non-excluded sessions.

    Also attaches clearly labeled all-visible (non-excluded) operational totals so
    Review can show raw day activity without conflating it with Performance.
    """
    sessions = list(emp.get("sessions") or [])
    included: list[dict[str, Any]] = []
    visible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for raw in sessions:
        sess = dict(raw)
        if session_is_excluded(sess):
            excluded.append(sess)
            continue
        if session_is_visible_non_excluded(sess):
            visible.append(sess)
        if session_is_included_for_metrics(sess):
            included.append(sess)
        elif session_is_visible_non_excluded(sess):
            pending.append(sess)

    calc_orders = sum(int(s.get("orders_completed") or 0) for s in included)
    calc_lbs = round(sum(float(s.get("total_pre_lbs") or 0) for s in included), 2)
    hours_vals = [
        float(s["performance_hours"])
        for s in included
        if s.get("performance_hours") is not None
    ]
    has_hours = bool(hours_vals)
    calc_hours = round(sum(hours_vals), 4) if has_hours else None

    vis_orders = sum(int(s.get("orders_completed") or 0) for s in visible)
    vis_lbs = round(sum(float(s.get("total_pre_lbs") or 0) for s in visible), 2)
    vis_hours_vals = [
        float(s["performance_hours"])
        for s in visible
        if s.get("performance_hours") is not None
    ]
    vis_hours = round(sum(vis_hours_vals), 4) if vis_hours_vals else None

    override = None
    if average_weight_override is not None:
        try:
            override = float(average_weight_override)
        except (TypeError, ValueError):
            override = None
        if override is not None and override < 0:
            override = None

    if override is not None and calc_orders > 0:
        effective_lbs = round(override * calc_orders, 2)
        avg_weight = override
        is_override = True
    else:
        effective_lbs = calc_lbs
        avg_weight = round(calc_lbs / calc_orders, 4) if calc_orders > 0 else None
        is_override = False

    rates = weighted_aggregate_rates(
        total_orders=calc_orders,
        total_pre_lbs=effective_lbs,
        total_session_hours=calc_hours if has_hours else None,
    )

    starts = [_parse_dt(s.get("start_time")) for s in included]
    starts = [t for t in starts if t]
    ends = [_parse_dt(s.get("end_time") or s.get("performance_end")) for s in included]
    ends = [t for t in ends if t]
    any_open = any(str(s.get("role_status") or "").lower() == "open" for s in included)

    # Authoritative Performance fields = approved subset only.
    emp["orders_completed"] = calc_orders
    emp["total_pre_lbs"] = effective_lbs
    emp["calculated_total_pre_lbs"] = calc_lbs
    emp["calculated_orders_completed"] = calc_orders
    emp["bags_per_hour"] = rates["bags_per_hour"]
    emp["lbs_per_hour"] = rates["lbs_per_hour"]
    emp["performance_hours"] = calc_hours
    emp["session_hours"] = calc_hours
    emp["session_count"] = len(sessions)
    emp["included_session_count"] = len(included)
    emp["approved_session_count"] = len(included)
    emp["pending_session_count"] = len(pending)
    emp["excluded_session_count"] = len(excluded)
    emp["visible_session_count"] = len(visible)
    # Operational all-visible totals (non-excluded) — not the Performance result.
    emp["all_visible_orders_completed"] = vis_orders
    emp["all_visible_total_pre_lbs"] = vis_lbs
    emp["all_visible_performance_hours"] = vis_hours
    emp["day_average_weight"] = avg_weight
    emp["day_average_weight_override"] = override if is_override else None
    emp["day_average_weight_is_override"] = is_override
    emp["credited_weight_basis"] = (
        "DAY_AVERAGE_WEIGHT_OVERRIDE" if is_override else "EVIDENCE_PRE"
    )
    emp["aggregate_method"] = "weighted_totals_approved_non_excluded"
    emp["metrics_basis"] = DASHBOARD_ELIGIBILITY
    emp["duration_label"] = _fmt_duration_hours(calc_hours)
    if starts or ends:
        from backend.management_wf_folder_performance import _fmt_clock  # noqa: PLC0415

        emp["time_range_label"] = (
            f"{_fmt_clock(min(starts)) if starts else '—'} – "
            f"{'Open' if any_open else (_fmt_clock(max(ends)) if ends else '—')}"
        )
    return emp


def apply_publication_and_day_metrics(
    cursor,
    organization_id: int,
    day: dict[str, Any],
) -> dict[str, Any]:
    """After session publication stamps exist, recompute included-only day metrics."""
    selected = day.get("selected_date_et") or day.get("business_date_et")
    biz: date | None = None
    if isinstance(selected, date):
        biz = selected
    elif selected:
        try:
            biz = date.fromisoformat(str(selected)[:10])
        except ValueError:
            biz = None

    overrides: dict[str, float] = {}
    if biz is not None:
        # Ensure tables exist on Performance GET (annotate path), not only on Edit Day.
        ensure_employee_day_override_tables(cursor)
        overrides = load_day_average_weight_overrides(
            cursor,
            organization_id,
            role_key=ROLE_FOLDER,
            business_date_et=biz,
        )

    for emp in day.get("employees") or []:
        try:
            key = employee_day_override_key(
                employee_user_id=emp.get("user_id"),
                employee_name=str(emp.get("employee") or ""),
            )
        except ValueError:
            key = ""
        ov = overrides.get(key) if key else None
        recompute_employee_day_metrics(emp, average_weight_override=ov)

    # Top-level session list is audit-oriented; leave raw. Summary recomputed later
    # by partition_employees_by_exclusion from employee cards.
    return day


def pick_final_included_session(
    sessions: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Last included Folder session by effective chronological end.

    Sort key is performance_end / end_time (not session_id, not array order).
    Excluded sessions are ignored even if they end later. Folder Performance
    payloads only contain Folder sessions, so non-Folder roles never appear.
    """
    candidates: list[tuple[datetime, int, dict[str, Any]]] = []
    for raw in sessions:
        sess = dict(raw)
        if not session_is_included_for_metrics(sess):
            continue
        end = _parse_dt(sess.get("performance_end") or sess.get("end_time"))
        start = _parse_dt(sess.get("start_time"))
        key = end or start
        if key is None:
            continue
        # Tie-break only: stable among equal ends — still chronology-first.
        try:
            sid_tie = int(sess.get("session_id") or 0)
        except (TypeError, ValueError):
            sid_tie = 0
        candidates.append((key, sid_tie, sess))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[-1][2]


def apply_employee_day_end_time(
    conn,
    organization_id: int,
    *,
    selected_date_et: date,
    employee_name: str,
    employee_user_id: int | None,
    end_time_et: str,
    reason: str | None = None,
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    day: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Set ended_at on the final included Folder segment for the employee-day."""
    from backend.management_wf_folder_performance import build_day_folder_performance
    from backend.payroll_operations import update_time_record_segment
    from backend.rinse_performance_approvals import invalidate_approvals
    from backend.rinse_performance_folder_publisher import attach_publication_status_to_day

    cursor = conn.cursor(dictionary=True)
    ensure_employee_day_override_tables(cursor)

    day_payload = dict(day) if day else build_day_folder_performance(
        cursor,
        int(organization_id),
        selected_date_et=selected_date_et,
        attach_customers=False,
    )
    attach_publication_status_to_day(cursor, organization_id, day_payload)
    # Metrics filter excluded before picking final included session.
    apply_publication_and_day_metrics(cursor, organization_id, day_payload)

    target_emp = None
    name_cf = str(employee_name or "").strip().casefold()
    for emp in day_payload.get("employees") or []:
        if employee_user_id is not None and emp.get("user_id") is not None:
            if int(emp["user_id"]) == int(employee_user_id):
                target_emp = emp
                break
        if str(emp.get("employee") or "").strip().casefold() == name_cf:
            target_emp = emp
            break
    if not target_emp:
        return {"ok": False, "status": "employee_not_found"}

    final_sess = pick_final_included_session(target_emp.get("sessions") or [])
    if not final_sess:
        return {"ok": False, "status": "no_included_session"}

    sid_raw = final_sess.get("session_id")
    seg_raw = final_sess.get("segment_id")
    try:
        sid = int(sid_raw)
        seg_id = int(seg_raw)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "status": "invalid_session_segment",
            "session_id": sid_raw,
            "segment_id": seg_raw,
        }

    try:
        update_time_record_segment(
            conn,
            int(organization_id),
            sid,
            seg_id,
            ended_at=end_time_et,
            ended_at_provided=True,
        )
    except Exception as exc:  # noqa: BLE001 — surface validation to API
        return {"ok": False, "status": "segment_update_failed", "error": str(exc)}

    invalidate_approvals(
        cursor,
        organization_id,
        role_key=ROLE_FOLDER,
        session_ids=[str(sid)],
        reason="day_end_time_edit",
        actor_user_id=actor_user_id,
        actor_name=actor_name,
    )

    cursor.execute(
        f"""
        INSERT INTO {DAY_OVERRIDE_EVENTS_TABLE} (
          organization_id, role_key, business_date_et,
          employee_user_id, employee_name, action, end_time_et,
          target_session_id, target_segment_id,
          actor_user_id, actor_name, reason
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            int(organization_id),
            ROLE_FOLDER,
            selected_date_et,
            int(employee_user_id) if employee_user_id is not None else target_emp.get("user_id"),
            str(target_emp.get("employee") or employee_name),
            "SET_DAY_END_TIME",
            str(end_time_et)[:64],
            str(sid),
            seg_id,
            actor_user_id,
            actor_name,
            (reason or None) and str(reason)[:255],
        ),
    )
    return {
        "ok": True,
        "employee": target_emp.get("employee"),
        "session_id": str(sid),
        "segment_id": seg_id,
        "end_time_et": end_time_et,
        "business_date_et": selected_date_et.isoformat(),
    }


# ---------------------------------------------------------------------------
# Mutation-response helpers (fast path — no full bag rebuild)
# ---------------------------------------------------------------------------
# Live Management Performance rates use APPROVED non-excluded sessions only.
# Pending / Needs Approval / Disapproved remain visible in Review but contribute
# zero until approved. Exclude zeros contribution and marks EXCLUDED.
# Fully APPROVED employee-days are dashboard_rankable for Published boards.
# DASHBOARD_ELIGIBILITY (module top) = approved_non_excluded.


def apply_session_publication_patch(
    sessions: Sequence[Mapping[str, Any]],
    *,
    session_id: str | None = None,
    publication: Mapping[str, Any] | None = None,
    session_ids: Sequence[str] | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Return shallow-copied sessions with one/many publication stamps updated."""
    targets: set[str] = set()
    if session_id:
        targets.add(str(session_id).strip())
    for sid in session_ids or []:
        if sid:
            targets.add(str(sid).strip())
    pub = dict(publication or {})
    if status:
        pub["status"] = str(status).upper()
    st = str(pub.get("status") or status or "").upper()
    out: list[dict[str, Any]] = []
    for raw in sessions or []:
        sess = dict(raw)
        sid = str(sess.get("session_id") or "")
        if targets and sid in targets:
            sess["publication_status"] = st or sess.get("publication_status")
            prev = dict(sess.get("publication") or {})
            prev.update(pub)
            if st:
                prev["status"] = st
                prev["excluded"] = st == "EXCLUDED"
            sess["publication"] = prev
            sess["publication_status"] = prev.get("status") or st
        out.append(sess)
    return out


def compose_employee_day_from_sessions(
    *,
    employee_name: str,
    employee_user_id: int | None,
    sessions: Sequence[Mapping[str, Any]],
    average_weight_override: float | None = None,
    selected_date_et: date | str | None = None,
) -> dict[str, Any]:
    """Authoritative employee-day card from session facts + publication stamps.

    Does not touch bag attribution. Used after Approve/Exclude/Include/Unapprove/
    Edit Day average-weight so the UI can update without a full Performance rebuild.
    """
    from backend.rinse_performance_approvals import derive_employee_day_publication_status

    emp: dict[str, Any] = {
        "employee": employee_name,
        "user_id": employee_user_id,
        "sessions": [dict(s) for s in (sessions or [])],
        "selected_date_et": (
            selected_date_et.isoformat()
            if isinstance(selected_date_et, date)
            else (str(selected_date_et) if selected_date_et else None)
        ),
        "performance_unit": "employee_day",
        "metrics_basis": DASHBOARD_ELIGIBILITY,
    }
    recompute_employee_day_metrics(emp, average_weight_override=average_weight_override)
    day_pub = derive_employee_day_publication_status(emp["sessions"])
    emp["day_publication_status"] = day_pub["status"]
    emp["day_publication"] = day_pub
    emp["publication_status"] = day_pub["status"]
    # Rankable for approved-only team boards; Performance rates use approved subset.
    emp["dashboard_rankable"] = day_pub["status"] == "APPROVED"
    emp["eligibility_rule"] = DASHBOARD_ELIGIBILITY
    return emp


def load_override_for_employee(
    cursor,
    organization_id: int,
    *,
    business_date_et: date,
    employee_user_id: int | None,
    employee_name: str,
    role_key: str = ROLE_FOLDER,
) -> float | None:
    overrides = load_day_average_weight_overrides(
        cursor,
        organization_id,
        role_key=role_key,
        business_date_et=business_date_et,
    )
    try:
        key = employee_day_override_key(
            employee_user_id=employee_user_id,
            employee_name=employee_name,
        )
    except ValueError:
        return None
    return overrides.get(key)


def mutation_employee_day_payload(
    cursor,
    organization_id: int,
    *,
    selected_date_et: date,
    employee_name: str,
    employee_user_id: int | None,
    sessions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build employee_day + compact summary fields for mutation API responses."""
    ov = load_override_for_employee(
        cursor,
        organization_id,
        business_date_et=selected_date_et,
        employee_user_id=employee_user_id,
        employee_name=employee_name,
    )
    emp = compose_employee_day_from_sessions(
        employee_name=employee_name,
        employee_user_id=employee_user_id,
        sessions=sessions,
        average_weight_override=ov,
        selected_date_et=selected_date_et,
    )
    return {
        "employee_day": emp,
        "performance_unit": "employee_day",
        "eligibility_rule": DASHBOARD_ELIGIBILITY,
        "eligibility_note": (
            "Performance rates use APPROVED non-excluded sessions only. "
            "Pending sessions stay visible in Review but contribute zero until "
            "approved. Exclude removes a session from calculations. "
            "dashboard_rankable requires a fully APPROVED employee-day."
        ),
    }
