"""Payroll funding forecast — projected payout from schedule (not final payroll batch)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from backend.payroll_identity import payroll_week_bounds
from backend.payroll_schedule import (
    SCHEDULE_STATUSES,
    _cursor,
    _d,
    _q2,
    get_org_schedule_settings,
    seed_schedule_defaults,
)
from backend.ta_helpers import json_safe, table_exists, table_has_column

FORECAST_INCLUDE_STATUSES = frozenset({"scheduled", "completed", "clocked_in"})
FORECAST_EXCLUDE_STATUSES = frozenset({"cancelled", "replaced", "absent", "no_show"})
FORECAST_SICK_STATUSES = frozenset({"sick"})

CATEGORY_KEYS = ("w2", "contractor_1099", "temp")
CATEGORY_LABELS = {
    "w2": "W-2",
    "contractor_1099": "1099",
    "temp": "Temp",
    "tryout": "Try Out",
    "default": "All",
}


def ensure_payroll_calendar_settings(cursor) -> None:
    if table_exists(cursor, "payroll_calendar_settings"):
        return
    import pathlib

    sql_path = pathlib.Path(__file__).resolve().parent / "sql" / "payroll_calendar_settings_v1.sql"
    raw = sql_path.read_text(encoding="utf-8")
    c = cursor if hasattr(cursor, "execute") else cursor.cursor()
    for stmt in raw.split(";"):
        s = stmt.strip()
        if s and not s.startswith("--"):
            c.execute(s)


def _default_calendar_row(organization_id: int, worker_category: str, org_settings: dict) -> dict[str, Any]:
    week_start = int(org_settings.get("week_starts_on") or 0)
    payment_day = int(org_settings.get("payment_day_of_week") if org_settings.get("payment_day_of_week") is not None else 5)
    ot_default = float(org_settings.get("overtime_threshold_hours") or 40)
    ot_enabled = worker_category == "w2"
    return {
        "organization_id": int(organization_id),
        "worker_category": worker_category,
        "work_week_start_day": week_start,
        "work_week_end_day": (week_start + 6) % 7,
        "pay_frequency": "weekly",
        "payment_day_of_week": payment_day,
        "payment_lag_days": 0,
        "overtime_threshold_hours": ot_default,
        "overtime_enabled": ot_enabled,
        "overtime_multiplier": None,
        "include_draft_schedule_in_forecast": True,
        "include_published_schedule_in_forecast": True,
    }


def get_calendar_settings(conn, organization_id: int) -> dict[str, Any]:
    oid = int(organization_id)
    seed_schedule_defaults(conn.cursor(), oid)
    ensure_payroll_calendar_settings(conn.cursor())
    org_settings = get_org_schedule_settings(conn, oid)
    c = _cursor(conn)
    c.execute(
        "SELECT * FROM payroll_calendar_settings WHERE organization_id=%s ORDER BY worker_category",
        (oid,),
    )
    rows = {str(r["worker_category"]): dict(r) for r in c.fetchall()}
    categories = {}
    for cat in ("default", *CATEGORY_KEYS):
        raw = rows.get(cat) or rows.get("default")
        if raw:
            categories[cat] = json_safe(
                {
                    **raw,
                    "overtime_enabled": bool(raw.get("overtime_enabled")),
                    "include_draft_schedule_in_forecast": bool(raw.get("include_draft_schedule_in_forecast", 1)),
                    "include_published_schedule_in_forecast": bool(
                        raw.get("include_published_schedule_in_forecast", 1)
                    ),
                }
            )
        else:
            categories[cat] = _default_calendar_row(oid, cat, org_settings)
    return json_safe(
        {
            "organization_id": oid,
            "org_schedule_settings": org_settings,
            "categories": categories,
        }
    )


def save_calendar_settings(conn, organization_id: int, body: dict) -> dict[str, Any]:
    ensure_payroll_calendar_settings(conn.cursor())
    oid = int(organization_id)
    c = conn.cursor()
    items = body.get("categories") or body.get("items") or [body]
    if isinstance(items, dict):
        items = [{"worker_category": k, **v} for k, v in items.items()]
    for item in items:
        cat = str(item.get("worker_category") or "default")[:32]
        fields = (
            "work_week_start_day",
            "work_week_end_day",
            "pay_frequency",
            "payment_day_of_week",
            "payment_lag_days",
            "overtime_threshold_hours",
            "overtime_enabled",
            "overtime_multiplier",
            "include_draft_schedule_in_forecast",
            "include_published_schedule_in_forecast",
        )
        vals = [oid, cat]
        cols = ["organization_id", "worker_category"]
        updates = []
        for fld in fields:
            if fld in item:
                cols.append(fld)
                val = item[fld]
                if fld.startswith("overtime_enabled") or fld.startswith("include_"):
                    val = 1 if val else 0
                vals.append(val)
                updates.append(f"{fld}=VALUES({fld})")
        if len(cols) <= 2:
            continue
        placeholders = ", ".join(["%s"] * len(cols))
        c.execute(
            f"""
            INSERT INTO payroll_calendar_settings ({', '.join(cols)})
            VALUES ({placeholders})
            ON DUPLICATE KEY UPDATE {', '.join(updates)}
            """,
            tuple(vals),
        )
    return get_calendar_settings(conn, oid)


def _week_bounds_for_date(conn, organization_id: int, d: date, calendar: dict) -> tuple[date, date]:
    start_day = int(calendar.get("work_week_start_day") if calendar.get("work_week_start_day") is not None else 0)
    delta = (d.weekday() - start_day) % 7
    week_start = d - timedelta(days=delta)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def payment_date_for_week(week_start: date, calendar: dict) -> date:
    payment_dow = int(calendar.get("payment_day_of_week") if calendar.get("payment_day_of_week") is not None else 5)
    week_starts_on = int(calendar.get("work_week_start_day") or 0)
    lag = int(calendar.get("payment_lag_days") or 0)
    offset = (payment_dow - week_starts_on) % 7
    pay = week_start + timedelta(days=offset + lag)
    return pay


def _category_for_entry(entry: dict, profiles: dict[int, dict]) -> str:
    snap = entry.get("worker_category_snapshot")
    if snap:
        return str(snap)
    wpid = int(entry.get("worker_profile_id") or 0)
    prof = profiles.get(wpid) or {}
    return str(prof.get("worker_category") or "w2")


def _rate_for_entry(entry: dict, profiles: dict[int, dict]) -> Decimal:
    snap = entry.get("hourly_rate_snapshot")
    if snap is not None and _d(snap) > 0:
        return _d(snap)
    wpid = int(entry.get("worker_profile_id") or 0)
    prof = profiles.get(wpid) or {}
    if prof.get("default_hourly_rate") is not None:
        return _d(prof["default_hourly_rate"])
    return Decimal("0")


def _cost_for_entry(entry: dict, profiles: dict[int, dict]) -> Decimal:
    if entry.get("estimated_cost") is not None and _d(entry["estimated_cost"]) > 0:
        return _d(entry["estimated_cost"])
    hrs = _d(entry.get("scheduled_hours") or 0)
    rate = _rate_for_entry(entry, profiles)
    return hrs * rate if rate > 0 else Decimal("0")


def _calendar_for_category(calendar_bundle: dict, category: str) -> dict:
    cats = calendar_bundle.get("categories") or {}
    return cats.get(category) or cats.get("default") or {}


def _entry_in_forecast(
    entry: dict,
    *,
    include_draft: bool,
    include_published: bool,
) -> bool:
    status = str(entry.get("status") or "scheduled")
    if status in FORECAST_EXCLUDE_STATUSES:
        return False
    pub = str(entry.get("publish_status") or "draft")
    if pub == "published" and not include_published:
        return False
    if pub != "published" and not include_draft:
        return False
    return status in FORECAST_INCLUDE_STATUSES


def build_funding_forecast(
    conn,
    organization_id: int,
    *,
    as_of_date: Optional[str] = None,
    location_id: Optional[int] = None,
    worker_category: Optional[str] = None,
    include_draft: Optional[bool] = None,
    include_published: Optional[bool] = None,
    entries_override: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """
    Project payroll funding for the work week containing as_of_date.
    Uses schedule entry snapshots + worker profile fallbacks.
    """
    oid = int(organization_id)
    d = date.fromisoformat(str(as_of_date or date.today().isoformat())[:10])
    calendar_bundle = get_calendar_settings(conn, oid)
    default_cal = _calendar_for_category(calendar_bundle, "default")
    week_start, week_end = _week_bounds_for_date(conn, oid, d, default_cal)
    payment_date = payment_date_for_week(week_start, default_cal)

    inc_draft = include_draft if include_draft is not None else bool(default_cal.get("include_draft_schedule_in_forecast", True))
    inc_pub = include_published if include_published is not None else bool(
        default_cal.get("include_published_schedule_in_forecast", True)
    )

    c = _cursor(conn)
    profiles: dict[int, dict] = {}
    c.execute("SELECT * FROM payroll_worker_profiles WHERE organization_id=%s", (oid,))
    for p in c.fetchall():
        profiles[int(p["id"])] = dict(p)

    if entries_override is not None:
        entries = entries_override
    else:
        q = """
            SELECT e.*,
                   COALESCE(e.shift_snapshot, s.name) AS shift_name,
                   COALESCE(e.role_snapshot, r.name) AS role_name,
                   COALESCE(e.work_stream_snapshot, ws.name) AS work_stream_name,
                   COALESCE(NULLIF(TRIM(CONCAT(pp.first_name,' ',pp.last_name)), ''), u.username) AS worker_name
            FROM payroll_schedule_entries e
            JOIN payroll_worker_profiles p ON p.id=e.worker_profile_id
            JOIN users u ON u.id=p.user_id
            LEFT JOIN payroll_profiles pp ON pp.user_id=u.id
            LEFT JOIN payroll_shifts s ON s.id=e.shift_id
            LEFT JOIN payroll_work_streams ws ON ws.id=e.work_stream_id
            LEFT JOIN payroll_roles r ON r.id=e.role_id
            WHERE e.organization_id=%s AND e.work_date BETWEEN %s AND %s
        """
        params: list[Any] = [oid, week_start.isoformat(), week_end.isoformat()]
        if location_id:
            q += " AND (e.geofence_id=%s OR e.geofence_id IS NULL)"
            params.append(int(location_id))
        c.execute(q, tuple(params))
        entries = [dict(r) for r in c.fetchall()]

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    daily: dict[str, dict] = {
        day_names[i]: {"date": (week_start + timedelta(days=i)).isoformat(), "people": set(), "hours": Decimal("0"), "cost": Decimal("0")}
        for i in range(7)
    }
    by_shift: dict[str, dict] = {}
    by_stream: dict[str, dict] = {}
    by_role: dict[str, dict] = {}
    by_category: dict[str, dict] = {
        k: {"label": CATEGORY_LABELS.get(k, k), "hours": Decimal("0"), "cost": Decimal("0"), "draft_cost": Decimal("0"), "published_cost": Decimal("0")}
        for k in CATEGORY_KEYS
    }
    worker_acc: dict[int, dict] = {}
    sick_hours = Decimal("0")
    sick_cost = Decimal("0")
    absent_count = 0
    excluded_replaced = 0

    total_cost = Decimal("0")
    total_hours = Decimal("0")
    draft_cost = Decimal("0")
    published_cost = Decimal("0")

    for entry in entries:
        status = str(entry.get("status") or "scheduled")
        if status in FORECAST_EXCLUDE_STATUSES:
            if status == "replaced":
                excluded_replaced += 1
            if status in ("absent", "no_show"):
                absent_count += 1
            continue
        if status in FORECAST_SICK_STATUSES:
            hrs = _d(entry.get("scheduled_hours") or 0)
            sick_hours += hrs
            sick_cost += _cost_for_entry(entry, profiles)
            continue

        cat = _category_for_entry(entry, profiles)
        if worker_category and cat != worker_category:
            continue

        cal = _calendar_for_category(calendar_bundle, cat)
        if not _entry_in_forecast(entry, include_draft=inc_draft, include_published=inc_pub):
            continue

        hrs = _d(entry.get("scheduled_hours") or 0)
        cost = _cost_for_entry(entry, profiles)
        total_hours += hrs
        total_cost += cost
        pub = str(entry.get("publish_status") or "draft")
        if pub == "published":
            published_cost += cost
        else:
            draft_cost += cost

        cat_key = cat if cat in by_category else "w2"
        by_category[cat_key]["hours"] += hrs
        by_category[cat_key]["cost"] += cost
        if pub == "published":
            by_category[cat_key]["published_cost"] += cost
        else:
            by_category[cat_key]["draft_cost"] += cost

        wd = date.fromisoformat(str(entry["work_date"])[:10])
        day_idx = (wd - week_start).days
        if 0 <= day_idx < 7:
            dn = day_names[day_idx]
            daily[dn]["people"].add(int(entry["worker_profile_id"]))
            daily[dn]["hours"] += hrs
            daily[dn]["cost"] += cost

        shift_name = entry.get("shift_name") or entry.get("shift_snapshot") or "Shift"
        stream_name = entry.get("work_stream_name") or entry.get("work_stream_snapshot") or "—"
        role_name = entry.get("role_name") or entry.get("role_snapshot") or "—"
        for bucket, key in ((by_shift, shift_name), (by_stream, stream_name), (by_role, role_name)):
            bucket.setdefault(key, {"hours": Decimal("0"), "cost": Decimal("0"), "people": set()})
            bucket[key]["hours"] += hrs
            bucket[key]["cost"] += cost
            bucket[key]["people"].add(int(entry["worker_profile_id"]))

        wpid = int(entry["worker_profile_id"])
        if wpid not in worker_acc:
            prof = profiles.get(wpid) or {}
            worker_acc[wpid] = {
                "worker_profile_id": wpid,
                "worker_name": entry.get("worker_name"),
                "worker_category": cat,
                "worker_category_label": CATEGORY_LABELS.get(cat, cat),
                "hourly_rate": _q2(_rate_for_entry(entry, profiles)),
                "scheduled_hours": Decimal("0"),
                "scheduled_days": set(),
                "projected_cost": Decimal("0"),
                "roles": set(),
                "streams": set(),
            }
        worker_acc[wpid]["scheduled_hours"] += hrs
        worker_acc[wpid]["projected_cost"] += cost
        worker_acc[wpid]["scheduled_days"].add(str(entry["work_date"])[:10])
        if role_name != "—":
            worker_acc[wpid]["roles"].add(role_name)
        if stream_name != "—":
            worker_acc[wpid]["streams"].add(stream_name)

    overtime_risks = []
    total_ot_hours = Decimal("0")
    total_ot_premium = Decimal("0")
    org_settings = calendar_bundle.get("org_schedule_settings") or {}

    for wpid, w in worker_acc.items():
        prof = profiles.get(wpid) or {}
        cat = str(w.get("worker_category") or "w2")
        cal = _calendar_for_category(calendar_bundle, cat)
        ot_enabled = bool(cal.get("overtime_enabled"))
        threshold = _d(cal.get("overtime_threshold_hours") or prof.get("overtime_threshold") or org_settings.get("overtime_threshold_hours") or 40)
        hrs = w["scheduled_hours"]
        regular = min(hrs, threshold) if ot_enabled else hrs
        ot_hrs = max(Decimal("0"), hrs - threshold) if ot_enabled else Decimal("0")
        rate = _d(w.get("hourly_rate") or 0)
        multiplier = cal.get("overtime_multiplier")
        ot_premium = Decimal("0")
        if ot_hrs > 0 and multiplier:
            ot_premium = ot_hrs * rate * (_d(multiplier) - Decimal("1"))
        total_ot_hours += ot_hrs
        total_ot_premium += ot_premium

        heavy = float(org_settings.get("heavy_hours_threshold") or 35)
        under = float(org_settings.get("underused_hours_threshold") or 15)
        h = float(hrs)
        if ot_hrs > 0:
            balance = "Overtime Risk"
        elif h >= heavy:
            balance = "Heavy"
        elif h < under and len(w["scheduled_days"]) <= 2:
            balance = "Underused"
        else:
            balance = "Balanced"

        w["regular_hours"] = _q2(regular)
        w["overtime_hours"] = _q2(ot_hrs)
        w["overtime_threshold"] = _q2(threshold)
        w["overtime_risk"] = ot_hrs > 0
        w["estimated_overtime_premium"] = _q2(ot_premium) if ot_premium > 0 else None
        w["balance_label"] = balance
        w["scheduled_hours"] = _q2(hrs)
        w["projected_cost"] = _q2(w["projected_cost"])
        w["scheduled_days"] = len(w["scheduled_days"])
        w["role_tags"] = sorted(w.pop("roles"))
        w["stream_tags"] = sorted(w.pop("streams"))

        if ot_hrs > 0:
            overtime_risks.append(
                {
                    "worker_profile_id": wpid,
                    "worker_name": w["worker_name"],
                    "worker_category": cat,
                    "scheduled_hours": w["scheduled_hours"],
                    "overtime_hours": w["overtime_hours"],
                    "overtime_threshold": w["overtime_threshold"],
                    "hourly_rate": w["hourly_rate"],
                }
            )

    worker_breakdown = sorted(worker_acc.values(), key=lambda x: -float(x.get("projected_cost") or 0))

    def _serialize_daily(daily_map):
        out = []
        for name in day_names:
            row = daily_map[name]
            out.append(
                {
                    "day": name,
                    "date": row["date"],
                    "people_count": len(row["people"]),
                    "hours": _q2(row["hours"]),
                    "cost": _q2(row["cost"]),
                }
            )
        return out

    def _serialize_bucket(bucket):
        return [
            {"name": k, "hours": _q2(v["hours"]), "cost": _q2(v["cost"]), "people_count": len(v["people"])}
            for k, v in sorted(bucket.items(), key=lambda x: -float(x[1]["cost"]))
        ]

    payment_label = payment_date.strftime("%A")
    return json_safe(
        {
            "estimated": True,
            "disclaimer": "Projected funding estimate from schedule — not final payroll.",
            "as_of_date": d.isoformat(),
            "payment_date": payment_date.isoformat(),
            "payment_day_label": payment_label,
            "card_title": f"Payroll Needed for {payment_label}",
            "work_week_start": week_start.isoformat(),
            "work_week_end": week_end.isoformat(),
            "total_projected_cost": _q2(total_cost),
            "total_scheduled_hours": _q2(total_hours),
            "draft_cost": _q2(draft_cost),
            "published_cost": _q2(published_cost),
            "category_breakdown": {
                k: {
                    "label": v["label"],
                    "hours": _q2(v["hours"]),
                    "cost": _q2(v["cost"]),
                    "draft_cost": _q2(v["draft_cost"]),
                    "published_cost": _q2(v["published_cost"]),
                }
                for k, v in by_category.items()
            },
            "daily_breakdown": _serialize_daily(daily),
            "shift_breakdown": _serialize_bucket(by_shift),
            "stream_breakdown": _serialize_bucket(by_stream),
            "role_breakdown": _serialize_bucket(by_role),
            "worker_breakdown": worker_breakdown,
            "overtime_risks": overtime_risks,
            "overtime_risk_count": len(overtime_risks),
            "projected_overtime_hours": _q2(total_ot_hours),
            "estimated_overtime_premium": _q2(total_ot_premium) if total_ot_premium > 0 else None,
            "sick_hours": _q2(sick_hours),
            "sick_cost": _q2(sick_cost),
            "absent_excluded_count": absent_count,
            "replaced_excluded_count": excluded_replaced,
            "warnings": [],
            "settings_used": {
                "include_draft": inc_draft,
                "include_published": inc_pub,
                "calendar": calendar_bundle,
            },
        }
    )
