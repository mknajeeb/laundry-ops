"""Tests for planned weekly schedule totals, move, org isolation, and exclusions."""

from __future__ import annotations

from datetime import date, time, timedelta
from unittest.mock import MagicMock, patch

from backend.planned_weekly_schedule import (
    allocate_role_hours_by_day,
    build_week_payload,
    bulk_set_week_entry_employer_affiliation,
    carry_forward_week_schedule,
    cascade_week_schedule,
    compute_schedule_totals,
    create_entry,
    delete_entry,
    duplicate_entry,
    ensure_week_schedule_carried_forward,
    find_latest_schedule_week_before,
    get_entry,
    list_excluded_user_ids,
    list_week_entries,
    move_entry,
    normalize_week_start,
    normalize_weekly_role,
    parse_weekly_roles,
    roles_to_storage,
    serialize_entry,
    set_employee_exclusion,
    update_entry,
    week_has_schedule_content,
)


class _FakeCursor:
    def __init__(self):
        self._id = 0
        self.rows: list[dict] = []
        self.exclusions: list[dict] = []
        self.roles: list[dict] = []
        self.groups: list[dict] = []
        self.responsibilities: list[dict] = []
        self._resp_id = 0
        self.org_state: dict[int, dict] = {}
        self.connection = object()
        self._rowcount = 0

    def _execute_org_state(self, sql_norm, params):
        if sql_norm.startswith("insert"):
            org_id = params[0]
            state = self.org_state.setdefault(org_id, {"organization_id": org_id})
            if "template_enabled" in sql_norm:
                _, enabled, source, user_id = params
                state.update(
                    {"template_enabled": enabled, "template_source_week": source, "template_updated_by": user_id}
                )
            else:
                state["cleaning_tasks_migrated_at"] = "migrated"
            return
        (org_id,) = params
        self._last = [dict(self.org_state[org_id])] if org_id in self.org_state else []

    def _execute_distinct_weeks(self, sql_norm, params):
        org_id, after = params
        if "planned_weekly_schedule_entries" in sql_norm:
            source = self.rows
        elif "planned_weekly_schedule_exclusions" in sql_norm:
            source = self.exclusions
        else:
            source = self.responsibilities
        if "count(*)" in sql_norm:
            counts: dict = {}
            for r in source:
                if r["organization_id"] == org_id and r["week_start"] > after:
                    counts[r["week_start"]] = counts.get(r["week_start"], 0) + 1
            self._last = [{"week_start": w, "n": n} for w, n in sorted(counts.items())]
            return
        weeks = sorted({r["week_start"] for r in source if r["organization_id"] == org_id and r["week_start"] > after})
        self._last = [{"week_start": w} for w in weeks]

    def _execute_roles(self, sql_norm, params):
        if "insert into weekly_schedule_roles" in sql_norm:
            org_id, code, name, group, order, active, timed, remarks = params
            row = {
                "organization_id": org_id,
                "code": code,
                "name": name,
                "role_group": group,
                "display_order": order,
                "active": active,
                "uses_time_slots": timed,
                "remarks_enabled": remarks,
            }
            self.roles = [
                r for r in self.roles if not (r["organization_id"] == org_id and r["code"] == code)
            ] + [row]
            return
        (org_id,) = params
        self._last = [r for r in self.roles if r["organization_id"] == org_id]

    def _execute_responsibilities(self, sql_norm, params):
        if sql_norm.startswith("insert"):
            org_id, week_start, user_id, dow, role, remarks = params
            if "insert ignore" in sql_norm and any(
                r["organization_id"] == org_id
                and r["week_start"] == week_start
                and r["user_id"] == user_id
                and r["day_of_week"] == dow
                and r["role"] == role
                for r in self.responsibilities
            ):
                return
            self._resp_id += 1
            self.responsibilities.append(
                {
                    "id": self._resp_id,
                    "organization_id": org_id,
                    "week_start": week_start,
                    "user_id": user_id,
                    "day_of_week": dow,
                    "role": role,
                    "remarks": remarks,
                }
            )
            self._id = self._resp_id
            return
        if sql_norm.startswith("update") and "set remarks = %s" in sql_norm:
            remarks, org_id, rid = params
            for r in self.responsibilities:
                if r["organization_id"] == org_id and r["id"] == rid:
                    r["remarks"] = remarks
            return
        if sql_norm.startswith("update"):
            user_id, dow, role, remarks, org_id, rid = params
            for r in self.responsibilities:
                if r["organization_id"] == org_id and r["id"] == rid:
                    r.update({"user_id": user_id, "day_of_week": dow, "role": role, "remarks": remarks})
            return
        if sql_norm.startswith("delete"):
            before = len(self.responsibilities)
            if "and id =" in sql_norm:
                org_id, rid = params
                self.responsibilities = [
                    r for r in self.responsibilities if not (r["organization_id"] == org_id and r["id"] == rid)
                ]
            elif "user_id" in sql_norm and "day_of_week >=" in sql_norm:
                org_id, user_id, week_start, min_dow = params
                self.responsibilities = [
                    r
                    for r in self.responsibilities
                    if not (
                        r["organization_id"] == org_id
                        and r["user_id"] == user_id
                        and r["week_start"] == week_start
                        and r["day_of_week"] >= min_dow
                    )
                ]
            elif "user_id" in sql_norm:
                org_id, user_id, week_start = params
                self.responsibilities = [
                    r
                    for r in self.responsibilities
                    if not (
                        r["organization_id"] == org_id and r["user_id"] == user_id and r["week_start"] > week_start
                    )
                ]
            else:
                org_id, week_start = params
                self.responsibilities = [
                    r
                    for r in self.responsibilities
                    if not (r["organization_id"] == org_id and r["week_start"] == week_start)
                ]
            self._rowcount = before - len(self.responsibilities)
            return
        if "and id =" in sql_norm:
            org_id, rid = params
            self._last = [r for r in self.responsibilities if r["organization_id"] == org_id and r["id"] == rid]
            return
        if "and role =" in sql_norm:
            org_id, week_start, user_id, dow, role = params
            self._last = [
                r
                for r in self.responsibilities
                if r["organization_id"] == org_id
                and r["week_start"] == week_start
                and r["user_id"] == user_id
                and r["day_of_week"] == dow
                and r["role"] == role
            ]
            return
        org_id, week_start = params
        self._last = [
            r for r in self.responsibilities if r["organization_id"] == org_id and r["week_start"] == week_start
        ]

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split()).lower()
        params = params or ()
        if "show tables" in sql_norm or "information_schema" in sql_norm:
            self._last = [{"cnt": 1}]
            return
        if "create table" in sql_norm or sql_norm.startswith("alter table"):
            return
        if sql_norm.startswith("show columns"):
            self._last = [{"Field": "x", "Type": "varchar(64)"}]
            return
        if "weekly_schedule_org_state" in sql_norm:
            self._execute_org_state(sql_norm, params)
            return
        if sql_norm.startswith("select distinct week_start") or (
            "count(*) as n" in sql_norm and "group by week_start" in sql_norm
        ):
            self._execute_distinct_weeks(sql_norm, params)
            return
        if "weekly_schedule_role_groups" in sql_norm:
            if sql_norm.startswith("insert"):
                org_id, code, label, order, active = params
                self.groups = [g for g in self.groups if not (g["organization_id"] == org_id and g["code"] == code)]
                self.groups.append(
                    {"organization_id": org_id, "code": code, "label": label, "display_order": order, "active": active}
                )
            else:
                (org_id,) = params
                self._last = [g for g in self.groups if g["organization_id"] == org_id]
            return
        if "weekly_schedule_roles" in sql_norm:
            self._execute_roles(sql_norm, params)
            return
        if "update planned_weekly_schedule_entries" in sql_norm and "set role = %s, role_assignments = %s" in sql_norm:
            role, assignments, org_id, entry_id = params
            for row in self.rows:
                if row["organization_id"] == org_id and row["id"] == entry_id:
                    row.update({"role": role, "role_assignments": assignments})
            return
        if "planned_weekly_schedule_responsibilities" in sql_norm:
            self._execute_responsibilities(sql_norm, params)
            return
        if "insert ignore into planned_weekly_schedule_exclusions" in sql_norm:
            org_id, week_start, user_id = params
            if not any(
                r["organization_id"] == org_id
                and r["week_start"] == week_start
                and r["user_id"] == user_id
                for r in self.exclusions
            ):
                self.exclusions.append(
                    {"organization_id": org_id, "week_start": week_start, "user_id": user_id}
                )
            return
        if "delete from planned_weekly_schedule_exclusions" in sql_norm:
            if "week_start >=" in sql_norm and len(params) == 3:
                org_id, user_id, week_start = params
                before = len(self.exclusions)
                self.exclusions = [
                    r
                    for r in self.exclusions
                    if not (
                        r["organization_id"] == org_id
                        and r["user_id"] == user_id
                        and r["week_start"] >= week_start
                    )
                ]
                self._rowcount = before - len(self.exclusions)
                return
            if len(params) == 2:
                org_id, week_start = params
                before = len(self.exclusions)
                self.exclusions = [
                    r
                    for r in self.exclusions
                    if not (r["organization_id"] == org_id and r["week_start"] == week_start)
                ]
                self._rowcount = before - len(self.exclusions)
                return
            org_id, week_start, user_id = params
            before = len(self.exclusions)
            self.exclusions = [
                r
                for r in self.exclusions
                if not (
                    r["organization_id"] == org_id
                    and r["week_start"] == week_start
                    and r["user_id"] == user_id
                )
            ]
            self._rowcount = before - len(self.exclusions)
            return
        if "from planned_weekly_schedule_exclusions" in sql_norm:
            org_id, week_start = params
            self._last = [
                r
                for r in self.exclusions
                if r["organization_id"] == org_id and r["week_start"] == week_start
            ]
            return
        if "insert into planned_weekly_schedule_entries" in sql_norm:
            self._id += 1
            row = {
                "id": self._id,
                "organization_id": params[0],
                "week_start": params[1],
                "user_id": params[2],
                "day_of_week": params[3],
                "role": params[4],
                "start_time": params[5],
                "end_time": params[6],
                "break_minutes": params[7],
                "employer_affiliation": params[8] if len(params) > 8 else None,
                "role_assignments": params[9] if len(params) > 9 else None,
                "break_slots": params[10] if len(params) > 10 else None,
            }
            self.rows.append(row)
            return
        if "update payroll_worker_profiles" in sql_norm and "set business_entity=%s" in sql_norm:
            self._rowcount = 1
            return
        if "update planned_weekly_schedule_entries" in sql_norm:
            if "set employer_affiliation=%s" in sql_norm and "week_start=%s" in sql_norm:
                aff = params[0]
                org_id = params[1]
                week_start = params[2]
                user_ids = set(params[3:]) if len(params) > 3 else None
                count = 0
                for row in self.rows:
                    if row["organization_id"] != org_id or row["week_start"] != week_start:
                        continue
                    if user_ids is not None and row["user_id"] not in user_ids:
                        continue
                    row["employer_affiliation"] = aff
                    count += 1
                self._rowcount = count
                return
            if "set employer_affiliation=%s" in sql_norm and "and id=%s" in sql_norm:
                aff, org_id, entry_id = params
                count = 0
                for row in self.rows:
                    if row["organization_id"] == org_id and row["id"] == entry_id:
                        row["employer_affiliation"] = aff
                        count += 1
                self._rowcount = count
                return
            entry_id = params[-1]
            for row in self.rows:
                if row["id"] == entry_id:
                    row.update(
                        {
                            "user_id": params[0],
                            "day_of_week": params[1],
                            "role": params[2],
                            "start_time": params[3],
                            "end_time": params[4],
                            "break_minutes": params[5],
                            "employer_affiliation": params[6] if len(params) > 8 else row.get("employer_affiliation"),
                            "role_assignments": params[7] if len(params) > 9 else row.get("role_assignments"),
                            "break_slots": params[8] if len(params) > 10 else row.get("break_slots"),
                        }
                    )
            return
        if "delete from planned_weekly_schedule_entries" in sql_norm:
            # Future weeks for one user: week_start > %s AND user_id
            if "week_start >" in sql_norm and "user_id" in sql_norm and len(params) == 3:
                org_id, user_id, week_start = params
                before = len(self.rows)
                self.rows = [
                    r
                    for r in self.rows
                    if not (
                        r["organization_id"] == org_id
                        and r["user_id"] == user_id
                        and r["week_start"] > week_start
                    )
                ]
                self._rowcount = before - len(self.rows)
                return
            # Current week remaining days: week_start = %s AND day_of_week >= %s
            if "day_of_week >=" in sql_norm and len(params) == 4:
                org_id, user_id, week_start, min_dow = params
                before = len(self.rows)
                self.rows = [
                    r
                    for r in self.rows
                    if not (
                        r["organization_id"] == org_id
                        and r["user_id"] == user_id
                        and r["week_start"] == week_start
                        and int(r["day_of_week"]) >= int(min_dow)
                    )
                ]
                self._rowcount = before - len(self.rows)
                return
            # Week wipe: ... week_start = %s (not "... AND id = %s")
            if "week_start" in sql_norm and " id =" not in sql_norm and len(params) == 2:
                org_id, week_start = params
                before = len(self.rows)
                self.rows = [
                    r
                    for r in self.rows
                    if not (r["organization_id"] == org_id and r["week_start"] == week_start)
                ]
                self._rowcount = before - len(self.rows)
                return
            org_id, entry_id = params
            before = len(self.rows)
            self.rows = [r for r in self.rows if not (r["organization_id"] == org_id and r["id"] == entry_id)]
            self._rowcount = before - len(self.rows)
            return
        if "from planned_weekly_schedule_entries" in sql_norm:
            if "and id =" in sql_norm:
                org_id, entry_id = params
                self._last = [r for r in self.rows if r["organization_id"] == org_id and r["id"] == entry_id]
            elif "week_start <" in sql_norm and "group by week_start" in sql_norm:
                org_id, before_week = params
                weeks = sorted(
                    {
                        r["week_start"]
                        for r in self.rows
                        if r["organization_id"] == org_id and r["week_start"] < before_week
                    },
                    reverse=True,
                )
                self._last = [{"week_start": weeks[0]}] if weeks else []
            elif len(params) == 1:
                (org_id,) = params
                self._last = [r for r in self.rows if r["organization_id"] == org_id]
            elif "week_start >= %s" in sql_norm:
                org_id, from_week = params
                self._last = [
                    r for r in self.rows if r["organization_id"] == org_id and r["week_start"] >= from_week
                ]
            else:
                org_id, week_start = params
                self._last = [
                    r
                    for r in self.rows
                    if r["organization_id"] == org_id and r["week_start"] == week_start
                ]
            return

    def executemany(self, sql, params_list):
        for params in params_list:
            self.execute(sql, params)

    def fetchone(self):
        rows = getattr(self, "_last", [])
        return rows[0] if rows else None

    def fetchall(self):
        return list(getattr(self, "_last", []))

    @property
    def lastrowid(self):
        return self._id

    @property
    def rowcount(self):
        return self._rowcount


def _mock_workers():
    return [
        {"user_id": 10, "id": 1, "display_name": "Alice", "default_hourly_rate": 19.5, "active": True},
        {"user_id": 20, "id": 2, "display_name": "Bob", "default_hourly_rate": 20.0, "active": True},
    ]


def test_normalize_week_start_snaps_to_sunday():
    assert normalize_week_start("2026-06-18") == date(2026, 6, 14)
    assert normalize_week_start(date(2026, 6, 14)) == date(2026, 6, 14)


def test_normalize_weekly_role_legacy_and_new():
    assert normalize_weekly_role("folder") == "fold"
    assert normalize_weekly_role("operator") == "wash"
    assert normalize_weekly_role("weigher") == "weigher"
    assert normalize_weekly_role("hd_operator") == "hd_operator"
    assert normalize_weekly_role("hd folder") == "hd_folder"
    assert normalize_weekly_role("attendant") == "attendant"
    assert normalize_weekly_role("non-rinse folder") == "non_rinse_folder"
    assert normalize_weekly_role("sort") == "sort"
    assert normalize_weekly_role("pt_sorter") == "pt_sorter"
    assert normalize_weekly_role("PT Washer") == "pt_washer"
    assert normalize_weekly_role("pt fold") == "pt_folder"
    assert parse_weekly_roles("wash,fold") == ["wash", "fold"]
    assert parse_weekly_roles("wash,weigher") == ["wash", "weigher"]
    assert parse_weekly_roles("hd_operator,hd_folder") == ["hd_operator", "hd_folder"]
    assert parse_weekly_roles("pt_washer,pt_sorter,pt_folder") == ["pt_sorter", "pt_washer", "pt_folder"]
    assert roles_to_storage(["fold", "sort", "wash", "weigher", "hd_operator"]) == "sort,wash,weigher,fold,hd_operator"
    assert roles_to_storage(["pt_folder", "pt_washer"]) == "pt_washer,pt_folder"


def test_allocate_role_hours_from_split_role_segments():
    entries = [
        serialize_entry(
            {
                "id": 1,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 10,
                "day_of_week": 0,
                "role": "wash",
                "start_time": time(6, 45),
                "end_time": time(7, 15),
                "break_minutes": 0,
            }
        ),
        serialize_entry(
            {
                "id": 2,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 10,
                "day_of_week": 0,
                "role": "fold",
                "start_time": time(8, 0),
                "end_time": time(15, 0),
                "break_minutes": 0,
            }
        ),
        serialize_entry(
            {
                "id": 3,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 10,
                "day_of_week": 0,
                "role": "sort",
                "start_time": time(15, 0),
                "end_time": time(17, 0),
                "break_minutes": 0,
            }
        ),
        serialize_entry(
            {
                "id": 4,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 10,
                "day_of_week": 0,
                "role": "sort",
                "start_time": time(17, 0),
                "end_time": time(18, 0),
                "break_minutes": 0,
            }
        ),
    ]
    hours = allocate_role_hours_by_day(entries)
    assert hours[0]["wash"] == 0.5
    assert hours[0]["fold"] == 7.0
    assert hours[0]["sort"] == 3.0


def test_allocate_role_hours_keeps_pt_roles_separate_and_splits_multi_role():
    entries = [
        serialize_entry(
            {
                "id": 1,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 10,
                "day_of_week": 0,
                "role": "sort,wash",
                "start_time": time(8, 0),
                "end_time": time(12, 0),
                "break_minutes": 0,
            }
        ),
        serialize_entry(
            {
                "id": 2,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 11,
                "day_of_week": 0,
                "role": "pt_washer",
                "start_time": time(8, 0),
                "end_time": time(14, 0),
                "break_minutes": 0,
            }
        ),
    ]
    hours = allocate_role_hours_by_day(entries)
    assert hours[0]["sort"] == 2.0
    assert hours[0]["wash"] == 2.0
    assert hours[0]["pt_washer"] == 6.0
    assert hours[0]["fold"] == 0.0


def test_allocate_role_hours_overnight_and_overlap_no_double_count():
    overnight = serialize_entry(
        {
            "id": 1,
            "organization_id": 1,
            "week_start": date(2026, 6, 14),
            "user_id": 10,
            "day_of_week": 0,
            "role": "fold",
            "start_time": time(22, 0),
            "end_time": time(2, 0),
            "break_minutes": 0,
        }
    )
    assert overnight["hours"] == 4.0
    assert allocate_role_hours_by_day([overnight])[0]["fold"] == 4.0

    overlapping = [
        serialize_entry(
            {
                "id": 2,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 10,
                "day_of_week": 1,
                "role": "wash",
                "start_time": time(8, 0),
                "end_time": time(12, 0),
                "break_minutes": 0,
            }
        ),
        serialize_entry(
            {
                "id": 3,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 10,
                "day_of_week": 1,
                "role": "wash",
                "start_time": time(10, 0),
                "end_time": time(14, 0),
                "break_minutes": 0,
            }
        ),
    ]
    assert allocate_role_hours_by_day(overlapping)[1]["wash"] == 6.0


def test_compute_schedule_totals_includes_pt_role_hours():
    entries = [
        serialize_entry(
            {
                "id": 1,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 10,
                "day_of_week": 0,
                "role": "pt_sorter",
                "start_time": time(9, 0),
                "end_time": time(13, 0),
                "break_minutes": 0,
            }
        ),
        serialize_entry(
            {
                "id": 2,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 10,
                "day_of_week": 0,
                "role": "wash",
                "start_time": time(13, 0),
                "end_time": time(15, 0),
                "break_minutes": 0,
            }
        ),
    ]
    totals = compute_schedule_totals(entries, {10: {"default_hourly_rate": 20.0}})
    sun = totals["day_totals"][0]
    assert sun["pt_sorter_count"] == 1
    assert sun["pt_sorter_hours"] == 4.0
    assert sun["wash_count"] == 1
    assert sun["wash_hours"] == 2.0
    assert sun["sort_hours"] == 0.0


def test_serialize_entry_days_only_has_zero_hours():
    entry = serialize_entry(
        {
            "id": 1,
            "organization_id": 1,
            "week_start": date(2026, 6, 14),
            "user_id": 10,
            "day_of_week": 1,
            "role": "wash",
            "start_time": time(9, 0),
            "end_time": time(16, 0),
            "break_minutes": 0,
        },
        schedule_end_time_enabled=False,
    )
    assert entry["hours"] == 0.0
    assert entry["start_time"] == "09:00"


def test_shift_hours_nine_to_four_is_seven():
    entry = serialize_entry(
        {
            "id": 1,
            "organization_id": 1,
            "week_start": date(2026, 6, 14),
            "user_id": 10,
            "day_of_week": 1,
            "role": "wash",
            "start_time": time(9, 0),
            "end_time": time(16, 0),
            "break_minutes": 0,
        }
    )
    assert entry["hours"] == 7.0


def test_shift_hours_two_pm_to_ten_pm_is_eight():
    entry = serialize_entry(
        {
            "id": 1,
            "organization_id": 1,
            "week_start": date(2026, 6, 14),
            "user_id": 10,
            "day_of_week": 1,
            "role": "wash",
            "start_time": time(14, 0),
            "end_time": time(22, 0),
            "break_minutes": 0,
        }
    )
    assert entry["hours"] == 8.0


def test_shift_hours_four_pm_to_ten_pm_is_six():
    entry = serialize_entry(
        {
            "id": 1,
            "organization_id": 1,
            "week_start": date(2026, 6, 14),
            "user_id": 10,
            "day_of_week": 1,
            "role": "fold",
            "start_time": time(16, 0),
            "end_time": time(22, 0),
            "break_minutes": 0,
        }
    )
    assert entry["hours"] == 6.0


def test_shift_hours_subtracts_break_minutes():
    entry = serialize_entry(
        {
            "id": 1,
            "organization_id": 1,
            "week_start": date(2026, 6, 14),
            "user_id": 10,
            "day_of_week": 1,
            "role": "wash",
            "start_time": time(14, 0),
            "end_time": time(22, 0),
            "break_minutes": 30,
        }
    )
    assert entry["hours"] == 7.5


def test_compute_schedule_totals_employee_and_day_rollups():
    entries = [
        serialize_entry(
            {
                "id": 1,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 10,
                "day_of_week": 0,
                "role": "fold",
                "start_time": time(9, 0),
                "end_time": time(16, 0),
                "break_minutes": 0,
            }
        ),
        serialize_entry(
            {
                "id": 2,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 10,
                "day_of_week": 1,
                "role": "wash",
                "start_time": time(6, 0),
                "end_time": time(15, 0),
                "break_minutes": 0,
            }
        ),
        serialize_entry(
            {
                "id": 3,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 20,
                "day_of_week": 0,
                "role": "sort,wash",
                "start_time": time(8, 0),
                "end_time": time(12, 0),
                "break_minutes": 0,
            }
        ),
    ]
    workers = {10: {"default_hourly_rate": 19.5}, 20: {"default_hourly_rate": 20.0}}
    totals = compute_schedule_totals(entries, workers)

    assert totals["employee_totals"][10]["total_hours"] == 16.0
    assert totals["employee_totals"][10]["scheduled_days"] == 2
    assert totals["employee_totals"][10]["estimated_cost"] == 312.0

    sun = totals["day_totals"][0]
    assert sun["employee_count"] == 2
    assert sun["total_hours"] == 11.0
    assert sun["wash_count"] == 1
    assert sun["fold_count"] == 1
    assert sun["sort_count"] == 1


def test_compute_schedule_totals_skips_excluded_employees():
    entries = [
        serialize_entry(
            {
                "id": 1,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 10,
                "day_of_week": 0,
                "role": "fold",
                "start_time": time(9, 0),
                "end_time": time(16, 0),
                "break_minutes": 0,
            }
        ),
        serialize_entry(
            {
                "id": 2,
                "organization_id": 1,
                "week_start": date(2026, 6, 14),
                "user_id": 20,
                "day_of_week": 0,
                "role": "wash",
                "start_time": time(8, 0),
                "end_time": time(12, 0),
                "break_minutes": 0,
            }
        ),
    ]
    workers = {10: {"default_hourly_rate": 19.5}, 20: {"default_hourly_rate": 20.0}}
    totals = compute_schedule_totals(entries, workers, excluded_user_ids=[10])

    assert 10 not in totals["employee_totals"]
    assert totals["employee_totals"][20]["total_hours"] == 4.0
    sun = totals["day_totals"][0]
    assert sun["employee_count"] == 1
    assert sun["total_hours"] == 4.0
    assert sun["operator_count"] == 1
    assert sun["wash_count"] == 1
    assert sun["folder_count"] == 0


def test_set_employee_exclusion_toggle():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 14)
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ):
        excluded, err = set_employee_exclusion(
            conn, cursor, 1, week_start=week, user_id=10, excluded=True
        )
    assert err is None
    assert excluded is True
    assert list_excluded_user_ids(cursor, 1, week_start=week) == [10]

    with patch("backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()):
        included, err = set_employee_exclusion(
            conn, cursor, 1, week_start=week, user_id=10, excluded=False
        )
    assert err is None
    assert included is False
    assert list_excluded_user_ids(cursor, 1, week_start=week) == []


def test_build_week_payload_marks_excluded_employees():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 14)
    cursor.exclusions.append({"organization_id": 1, "week_start": week, "user_id": 10})
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ), patch(
        "backend.planned_weekly_schedule.list_week_entries",
        return_value=[
            serialize_entry(
                {
                    "id": 1,
                    "organization_id": 1,
                    "week_start": week,
                    "user_id": 10,
                    "day_of_week": 0,
                    "role": "fold",
                    "start_time": time(9, 0),
                    "end_time": time(16, 0),
                    "break_minutes": 0,
                }
            )
        ],
    ):
        payload = build_week_payload(conn, cursor, 1, week_start=week)

    alice = next(e for e in payload["employees"] if e["user_id"] == 10)
    bob = next(e for e in payload["employees"] if e["user_id"] == 20)
    assert alice["excluded"] is True
    assert alice["total_hours"] == 0.0
    assert bob["excluded"] is False
    assert payload["excluded_user_ids"] == [10]
    assert payload["totals"]["day_totals"][0]["employee_count"] == 0


def test_move_entry_updates_user_and_day():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 14)
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ):
        created, err = create_entry(
            conn,
            cursor,
            1,
            week_start=week,
            data={
                "user_id": 10,
                "day_of_week": 0,
                "role": "fold",
                "start_time": "09:00",
                "end_time": "16:00",
            },
        )
    assert err is None
    with patch("backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()):
        moved, err = move_entry(conn, cursor, 1, created["id"], user_id=20, day_of_week=3)
    assert err is None
    assert moved["user_id"] == 20
    assert moved["day_of_week"] == 3


def test_duplicate_entry_creates_copy():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 14)
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ):
        created, err = create_entry(
            conn,
            cursor,
            1,
            week_start=week,
            data={
                "user_id": 10,
                "day_of_week": 2,
                "role": "wash",
                "start_time": "06:00",
                "end_time": "15:00",
            },
        )
    assert err is None
    with patch("backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()):
        copied, err = duplicate_entry(conn, cursor, 1, created["id"], day_of_week=4)
    assert err is None
    assert copied["id"] != created["id"]
    assert copied["day_of_week"] == 4
    assert copied["role"] == "wash"


def test_duplicate_entry_preserves_multi_role():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 14)
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ):
        created, err = create_entry(
            conn,
            cursor,
            1,
            week_start=week,
            data={
                "user_id": 10,
                "day_of_week": 1,
                "role": "sort,wash,fold",
                "start_time": "08:00",
                "end_time": "14:00",
            },
        )
    assert err is None
    with patch("backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()):
        copied, err = duplicate_entry(conn, cursor, 1, created["id"])
    assert err is None
    assert copied["role"] == "sort,wash,fold"
    assert copied["roles"] == ["sort", "wash", "fold"]


def test_create_and_update_entry_employer_affiliation():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 14)
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ), patch(
        "backend.payroll_schedule.worker_exists_in_schedule_grid",
        return_value=True,
    ):
        created, err = create_entry(
            conn,
            cursor,
            1,
            week_start=week,
            data={
                "user_id": 10,
                "day_of_week": 2,
                "role": "fold",
                "start_time": "09:00",
                "end_time": "16:00",
                "employer_affiliation": "rinse_exclusive",
            },
        )
        assert err is None
        assert created["employer_affiliation"] == "rinse_exclusive"

        updated, err = update_entry(
            conn,
            cursor,
            1,
            created["id"],
            {"employer_affiliation": "washpro"},
        )
        assert err is None
        assert updated["employer_affiliation"] == "washpro"


def test_duplicate_entry_without_stored_employer_uses_worker_default():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 14)
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ), patch(
        "backend.payroll_schedule.worker_exists_in_schedule_grid",
        return_value=True,
    ):
        created, err = create_entry(
            conn,
            cursor,
            1,
            week_start=week,
            data={
                "user_id": 10,
                "day_of_week": 1,
                "role": "fold",
                "start_time": "09:00",
                "end_time": "16:00",
            },
        )
        assert err is None
        created["employer_affiliation"] = None
        cursor.rows[-1]["employer_affiliation"] = None

        copied, err = duplicate_entry(conn, cursor, 1, created["id"])
        assert err is None
        assert copied["employer_affiliation"] == "washpro"


def test_org_isolation_on_get_and_delete():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 14)
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ):
        created, _ = create_entry(
            conn,
            cursor,
            1,
            week_start=week,
            data={
                "user_id": 10,
                "day_of_week": 0,
                "role": "fold",
                "start_time": "09:00",
                "end_time": "16:00",
            },
        )
    assert get_entry(cursor, 2, created["id"]) is None
    assert delete_entry(cursor, 2, created["id"]) is False
    assert get_entry(cursor, 1, created["id"]) is not None
    assert delete_entry(cursor, 1, created["id"]) is True
    assert get_entry(cursor, 1, created["id"]) is None
    assert list_week_entries(cursor, 1, week_start=week) == []


def test_update_entry_rejects_unknown_worker():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 14)
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ):
        created, _ = create_entry(
            conn,
            cursor,
            1,
            week_start=week,
            data={
                "user_id": 10,
                "day_of_week": 0,
                "role": "fold",
                "start_time": "09:00",
                "end_time": "16:00",
            },
        )
    with patch(
        "backend.payroll_schedule.worker_exists_in_schedule_grid",
        side_effect=lambda conn, org, uid: int(uid) in {10, 20},
    ):
        updated, err = update_entry(conn, cursor, 1, created["id"], {"user_id": 999})
    assert updated is None
    assert err == "worker not found in payroll profiles"


def test_find_latest_schedule_week_before():
    cursor = _FakeCursor()
    week_a = date(2026, 6, 7)
    week_b = date(2026, 6, 14)
    cursor.rows = [
        {"id": 1, "organization_id": 1, "week_start": week_a, "user_id": 10, "day_of_week": 0, "role": "fold", "start_time": time(9, 0), "end_time": time(16, 0), "break_minutes": 0},
        {"id": 2, "organization_id": 1, "week_start": week_b, "user_id": 10, "day_of_week": 1, "role": "wash", "start_time": time(9, 0), "end_time": time(16, 0), "break_minutes": 0},
        {"id": 3, "organization_id": 2, "week_start": week_b, "user_id": 99, "day_of_week": 0, "role": "fold", "start_time": time(9, 0), "end_time": time(16, 0), "break_minutes": 0},
    ]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True):
        assert find_latest_schedule_week_before(cursor, 1, before_week_start=date(2026, 6, 21)) == week_b
        assert find_latest_schedule_week_before(cursor, 1, before_week_start=week_b) == week_a
        assert find_latest_schedule_week_before(cursor, 1, before_week_start=week_a) is None


def test_cascade_week_schedule_requires_replace_when_target_has_content():
    cursor = _FakeCursor()
    conn = MagicMock()
    source = date(2026, 6, 14)
    target = date(2026, 6, 21)
    cursor.rows = [
        {
            "id": 1,
            "organization_id": 1,
            "week_start": source,
            "user_id": 10,
            "day_of_week": 1,
            "role": "wash",
            "start_time": time(9, 0),
            "end_time": time(16, 0),
            "break_minutes": 0,
        },
        {
            "id": 2,
            "organization_id": 1,
            "week_start": target,
            "user_id": 10,
            "day_of_week": 0,
            "role": "fold",
            "start_time": time(8, 0),
            "end_time": time(12, 0),
            "break_minutes": 0,
        },
    ]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ):
        result, err = cascade_week_schedule(
            conn,
            cursor,
            1,
            source_week_start=source,
            target_week_start=target,
            replace=False,
        )
        assert result is None
        assert "replace=true" in err

        result, err = cascade_week_schedule(
            conn,
            cursor,
            1,
            source_week_start=source,
            target_week_start=target,
            replace=True,
        )
    assert err is None
    assert result["replaced"] is True
    assert result["entries_deleted"] == 1
    assert result["entries_copied"] == 1
    copied = list_week_entries(cursor, 1, week_start=target)
    assert len(copied) == 1
    assert copied[0]["role"] == "wash"
    assert copied[0]["day_of_week"] == 1


def test_carry_forward_seeds_target_sunday_from_source_saturday_when_sunday_empty():
    cursor = _FakeCursor()
    conn = MagicMock()
    source = date(2026, 8, 16)
    target = date(2026, 8, 23)
    cursor.rows = [
        {
            "id": 1,
            "organization_id": 1,
            "week_start": source,
            "user_id": 10,
            "day_of_week": 6,
            "role": "fold",
            "start_time": time(8, 0),
            "end_time": time(16, 0),
            "break_minutes": 0,
        },
        {
            "id": 2,
            "organization_id": 1,
            "week_start": source,
            "user_id": 20,
            "day_of_week": 1,
            "role": "wash",
            "start_time": time(7, 0),
            "end_time": time(15, 0),
            "break_minutes": 0,
        },
    ]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ):
        result = carry_forward_week_schedule(
            conn,
            cursor,
            1,
            target_week_start=target,
            source_week_start=source,
        )
    assert result["entries_copied"] == 3
    copied = list_week_entries(cursor, 1, week_start=target)
    sunday = [e for e in copied if int(e["day_of_week"]) == 0]
    assert len(sunday) == 1
    assert sunday[0]["user_id"] == 10
    assert sunday[0]["role"] == "fold"


def test_cascade_week_schedule_copies_into_empty_target():
    cursor = _FakeCursor()
    conn = MagicMock()
    source = date(2026, 6, 14)
    target = date(2026, 6, 21)
    cursor.rows = [
        {
            "id": 1,
            "organization_id": 1,
            "week_start": source,
            "user_id": 10,
            "day_of_week": 2,
            "role": "pt_folder",
            "start_time": time(10, 0),
            "end_time": time(14, 0),
            "break_minutes": 0,
            "employer_affiliation": "rinse_exclusive",
        }
    ]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ):
        result, err = cascade_week_schedule(
            conn,
            cursor,
            1,
            source_week_start=source,
            target_week_start=target,
            replace=False,
        )
    assert err is None
    assert result["entries_copied"] == 1
    assert result["replaced"] is False
    copied = list_week_entries(cursor, 1, week_start=target)
    assert copied[0]["role"] == "pt_folder"
    assert copied[0]["employer_affiliation"] == "rinse_exclusive"


def test_carry_forward_week_schedule_copies_entries_and_exclusions():
    cursor = _FakeCursor()
    conn = MagicMock()
    source = date(2026, 6, 14)
    target = date(2026, 6, 21)
    cursor.rows = [
        {
            "id": 1,
            "organization_id": 1,
            "week_start": source,
            "user_id": 10,
            "day_of_week": 1,
            "role": "wash,fold",
            "start_time": time(9, 0),
            "end_time": time(16, 0),
            "break_minutes": 15,
        }
    ]
    cursor.exclusions.append({"organization_id": 1, "week_start": source, "user_id": 20})
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ):
        result = carry_forward_week_schedule(
            conn,
            cursor,
            1,
            target_week_start=target,
            source_week_start=source,
        )
    assert result["entries_copied"] == 1
    assert result["exclusions_copied"] == 1
    copied = list_week_entries(cursor, 1, week_start=target)
    assert len(copied) == 1
    assert copied[0]["user_id"] == 10
    assert copied[0]["day_of_week"] == 1
    assert copied[0]["role"] == "wash,fold"
    assert copied[0]["break_minutes"] == 15
    assert list_excluded_user_ids(cursor, 1, week_start=target) == [20]


def test_ensure_week_schedule_carried_forward_skips_when_target_has_content():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 21)
    cursor.rows = [
        {
            "id": 1,
            "organization_id": 1,
            "week_start": week,
            "user_id": 10,
            "day_of_week": 0,
            "role": "fold",
            "start_time": time(9, 0),
            "end_time": time(16, 0),
            "break_minutes": 0,
        }
    ]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True):
        assert week_has_schedule_content(cursor, 1, week_start=week) is True
        assert ensure_week_schedule_carried_forward(conn, cursor, 1, week_start=week) is None


def test_ensure_week_schedule_carried_forward_seeds_empty_week():
    cursor = _FakeCursor()
    conn = MagicMock()
    source = date(2026, 6, 14)
    target = date(2026, 6, 21)
    cursor.rows = [
        {
            "id": 1,
            "organization_id": 1,
            "week_start": source,
            "user_id": 10,
            "day_of_week": 2,
            "role": "sort",
            "start_time": time(8, 0),
            "end_time": time(14, 0),
            "break_minutes": 0,
        }
    ]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ):
        carry = ensure_week_schedule_carried_forward(conn, cursor, 1, week_start=target)
    assert carry is not None
    assert carry["source_week_start"] == str(source)
    assert carry["entries_copied"] == 1
    copied = list_week_entries(cursor, 1, week_start=target)
    assert len(copied) == 1
    assert copied[0]["day_of_week"] == 2


def test_bulk_set_week_entry_employer_affiliation():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 28)
    workers = [
        {"user_id": 10, "can_work_rinse": True, "can_work_drop_off": True, "can_work_both": True},
        {"user_id": 20, "can_work_rinse": True, "can_work_drop_off": False, "can_work_both": False},
    ]
    cursor.rows = [
        {
            "id": 1,
            "organization_id": 1,
            "week_start": week,
            "user_id": 10,
            "day_of_week": 0,
            "role": "fold",
            "start_time": time(9, 0),
            "end_time": time(16, 0),
            "break_minutes": 0,
            "employer_affiliation": "washpro",
        },
        {
            "id": 2,
            "organization_id": 1,
            "week_start": week,
            "user_id": 20,
            "day_of_week": 1,
            "role": "wash",
            "start_time": time(9, 0),
            "end_time": time(16, 0),
            "break_minutes": 0,
            "employer_affiliation": "washpro",
        },
    ]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers",
        return_value=workers,
    ), patch(
        "backend.payroll_employer_affiliation._organization_slug",
        return_value="washpro",
    ), patch(
        "backend.payroll_schedule.ensure_worker_profile",
    ):
        updated, err, skipped = bulk_set_week_entry_employer_affiliation(
            conn,
            cursor,
            1,
            week_start=week,
            employer_affiliation="rinse_exclusive",
        )
    assert err is None
    assert updated == 2
    assert skipped == []
    assert all(row["employer_affiliation"] == "rinse_exclusive" for row in cursor.rows)


def test_bulk_set_week_entry_employer_affiliation_migrates_cross_entity_worker():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 28)
    workers = [
        {"user_id": 10, "can_work_rinse": False, "can_work_drop_off": True, "can_work_both": False},
    ]
    cursor.rows = [
        {
            "id": 1,
            "organization_id": 1,
            "week_start": week,
            "user_id": 10,
            "day_of_week": 0,
            "role": "fold",
            "start_time": time(9, 0),
            "end_time": time(16, 0),
            "break_minutes": 0,
            "employer_affiliation": "washpro",
        },
    ]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers",
        return_value=workers,
    ), patch(
        "backend.payroll_employer_affiliation._organization_slug",
        return_value="washpro",
    ), patch(
        "backend.payroll_schedule.ensure_worker_profile",
    ):
        updated, err, skipped = bulk_set_week_entry_employer_affiliation(
            conn,
            cursor,
            1,
            week_start=week,
            employer_affiliation="rinse_exclusive",
        )
    assert err is None
    assert updated == 1
    assert skipped == []
    assert cursor.rows[0]["employer_affiliation"] == "rinse_exclusive"


def test_bulk_set_week_entry_employer_affiliation_moves_none_worker():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 28)
    workers = [
        {"user_id": 10, "can_work_rinse": False, "can_work_drop_off": False, "can_work_both": False},
    ]
    cursor.rows = [
        {
            "id": 1,
            "organization_id": 1,
            "week_start": week,
            "user_id": 10,
            "day_of_week": 0,
            "role": "fold",
            "start_time": time(9, 0),
            "end_time": time(16, 0),
            "break_minutes": 0,
            "employer_affiliation": "washpro",
        },
    ]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers",
        return_value=workers,
    ), patch(
        "backend.payroll_employer_affiliation._organization_slug",
        return_value="washpro",
    ), patch(
        "backend.payroll_schedule.ensure_worker_profile",
    ):
        updated, err, skipped = bulk_set_week_entry_employer_affiliation(
            conn,
            cursor,
            1,
            week_start=week,
            employer_affiliation="rinse_exclusive",
        )
    assert err is None
    assert updated == 1
    assert skipped == []
    assert cursor.rows[0]["employer_affiliation"] == "rinse_exclusive"


def test_clear_future_planned_keeps_historical_days():
    from backend.planned_weekly_schedule import clear_future_planned_schedule_entries_for_user

    cursor = _FakeCursor()
    # Week of Sun Aug 23; as_of = Fri Aug 28 → keep Sun–Thu, drop Fri–Sat + future weeks
    week = date(2026, 8, 23)
    future = date(2026, 8, 30)
    past = date(2026, 8, 16)
    for dow in range(7):
        cursor.rows.append(
            {
                "id": dow + 1,
                "organization_id": 3,
                "week_start": week,
                "user_id": 29,
                "day_of_week": dow,
                "role": "fold",
                "start_time": time(9, 0),
                "end_time": time(16, 0),
                "break_minutes": 0,
            }
        )
    cursor.rows.append(
        {
            "id": 100,
            "organization_id": 3,
            "week_start": future,
            "user_id": 29,
            "day_of_week": 0,
            "role": "sort",
            "start_time": time(7, 0),
            "end_time": time(15, 0),
            "break_minutes": 0,
        }
    )
    cursor.rows.append(
        {
            "id": 50,
            "organization_id": 3,
            "week_start": past,
            "user_id": 29,
            "day_of_week": 6,
            "role": "sort",
            "start_time": time(7, 0),
            "end_time": time(15, 0),
            "break_minutes": 0,
        }
    )
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True):
        deleted = clear_future_planned_schedule_entries_for_user(
            cursor, 3, 29, as_of=date(2026, 8, 28)
        )
    assert deleted >= 3
    remaining = [(r["week_start"], r["day_of_week"]) for r in cursor.rows if r["user_id"] == 29]
    assert (past, 6) in remaining
    assert (week, 0) in remaining  # Sunday kept
    assert (week, 4) in remaining  # Thursday kept
    assert (week, 5) not in remaining
    assert (week, 6) not in remaining
    assert (future, 0) not in remaining


def test_carry_forward_skips_affiliation_none_even_with_stale_source_rows():
    cursor = _FakeCursor()
    conn = MagicMock()
    source = date(2026, 8, 23)
    target = date(2026, 8, 30)
    cursor.rows = [
        {
            "id": 1,
            "organization_id": 3,
            "week_start": source,
            "user_id": 29,
            "day_of_week": 0,
            "role": "sort",
            "start_time": time(7, 0),
            "end_time": time(15, 0),
            "break_minutes": 0,
        },
        {
            "id": 2,
            "organization_id": 3,
            "week_start": source,
            "user_id": 10,
            "day_of_week": 1,
            "role": "fold",
            "start_time": time(9, 0),
            "end_time": time(16, 0),
            "break_minutes": 0,
        },
    ]
    workers = [
        {
            "user_id": 29,
            "display_name": "Paola",
            "business_entity": "none",
            "can_work_rinse": 0,
            "can_work_drop_off": 0,
            "can_work_both": 0,
            "active": 1,
        },
        {
            "user_id": 10,
            "display_name": "Alice",
            "business_entity": "veewash",
            "can_work_rinse": 0,
            "can_work_drop_off": 1,
            "can_work_both": 0,
            "active": 1,
        },
    ]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=workers
    ), patch(
        "backend.payroll_employer_affiliation._organization_slug", return_value="veewash"
    ):
        result = carry_forward_week_schedule(
            conn,
            cursor,
            3,
            target_week_start=target,
            source_week_start=source,
        )
    assert result["entries_skipped"] >= 1
    copied = list_week_entries(cursor, 3, week_start=target)
    assert all(int(e["user_id"]) != 29 for e in copied)
    assert any(int(e["user_id"]) == 10 for e in copied)


def test_build_week_payload_excludes_affiliation_none_worker():
    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 8, 23)
    cursor.rows = [
        {
            "id": 1,
            "organization_id": 3,
            "week_start": week,
            "user_id": 29,
            "day_of_week": 0,
            "role": "sort",
            "start_time": time(7, 0),
            "end_time": time(15, 0),
            "break_minutes": 0,
        },
        {
            "id": 2,
            "organization_id": 3,
            "week_start": week,
            "user_id": 10,
            "day_of_week": 1,
            "role": "fold",
            "start_time": time(9, 0),
            "end_time": time(16, 0),
            "break_minutes": 0,
        },
    ]
    workers = [
        {
            "user_id": 29,
            "worker_profile_id": 1,
            "display_name": "Paola",
            "business_entity": "none",
            "can_work_rinse": 0,
            "can_work_drop_off": 0,
            "can_work_both": 0,
            "default_hourly_rate": 17,
        },
        {
            "user_id": 10,
            "worker_profile_id": 2,
            "display_name": "Alice",
            "business_entity": "veewash",
            "can_work_rinse": 0,
            "can_work_drop_off": 1,
            "can_work_both": 0,
            "default_hourly_rate": 18,
        },
    ]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=workers
    ), patch(
        "backend.payroll_employer_affiliation._organization_slug", return_value="veewash"
    ), patch(
        "backend.weekly_schedule_display_settings.effective_weekly_schedule_view",
        return_value={"can_edit_schedule": True},
    ), patch(
        "backend.business_entity.entity_scope_payload",
        return_value={"organization_slug": "veewash"},
    ):
        payload = build_week_payload(conn, cursor, 3, week_start=week)
    assert all(int(e["user_id"]) != 29 for e in payload["employees"])
    assert all(int(e["user_id"]) != 29 for e in payload["entries"])
    assert any(int(e["user_id"]) == 10 for e in payload["employees"])


# --- Configurable roles, per-role time ranges, daily responsibilities ---------------------------

from backend.planned_weekly_schedule import scheduled_hours_by_user_day  # noqa: E402
from backend.planned_weekly_schedule_responsibilities import (  # noqa: E402
    create_responsibility,
    update_responsibility,
)
from backend.weekly_schedule_roles import create_role, list_role_catalog, update_role  # noqa: E402

WEEK = date(2026, 6, 14)


def _patched():
    return (
        patch("backend.planned_weekly_schedule.table_exists", return_value=True),
        patch("backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()),
    )


def _create(cursor, data):
    p1, p2 = _patched()
    with p1, p2:
        return create_entry(MagicMock(), cursor, 1, week_start=WEEK, data=data)


def test_role_catalog_includes_new_operational_roles():
    catalog = {r["code"]: r for r in list_role_catalog(_FakeCursor(), 1)}
    for code in ("lint_cleaning", "floor_cleaning", "washer_cleaning"):
        assert catalog[code]["uses_time_slots"] is False
        assert catalog[code]["kind"] == "task"
        assert catalog[code]["remarks_enabled"] is True
        assert catalog[code]["role_group"] == "CLEANING"
    for code in ("drop_off_customer", "self_service"):
        assert catalog[code]["uses_time_slots"] is False
        assert catalog[code]["kind"] == "task"
        assert catalog[code]["remarks_enabled"] is True
    for code in ("weigher", "sort", "wash", "dry", "fold", "post_weigh"):
        assert catalog[code]["kind"] == "role"
        assert catalog[code]["role_group"] == "RINSE_WF"
    orders = [r["display_order"] for r in catalog.values()]
    assert orders == sorted(orders)


def test_custom_role_create_and_builtin_override():
    cursor = _FakeCursor()
    role, err = create_role(cursor, 1, {"name": "Towel Restock", "role_group": "SELF_SERVICE"})
    assert err is None
    assert role["code"] == "custom_towel_restock"
    assert role["builtin"] is False
    _, err = create_role(cursor, 1, {"name": "towel restock"})
    assert err and "already exists" in err
    updated, err = update_role(cursor, 1, "sort", {"display_order": 5, "remarks_enabled": True})
    assert err is None and updated["display_order"] == 5 and updated["remarks_enabled"] is True
    catalog = list_role_catalog(cursor, 1)
    assert catalog[0]["code"] == "sort"
    assert any(r["code"] == "custom_towel_restock" for r in catalog)
    # Other orgs are unaffected.
    assert not any(r["code"] == "custom_towel_restock" for r in list_role_catalog(cursor, 2))


def test_role_time_ranges_inside_one_shift_count_hours_once():
    cursor = _FakeCursor()
    entry, err = _create(
        cursor,
        {
            "user_id": 10,
            "day_of_week": 1,
            "start_time": "02:00",
            "end_time": "08:00",
            "assignments": [
                {"role": "sort", "start_time": "02:00", "end_time": "05:00"},
                {"role": "wash", "start_time": "05:00", "end_time": "08:00"},
            ],
        },
    )
    assert err is None
    assert entry["hours"] == 6.0
    assert entry["roles"] == ["sort", "wash"]
    ranges = {(a["role"], a["start_time"], a["end_time"], a["full_shift"]) for a in entry["assignments"]}
    assert ranges == {("sort", "02:00", "05:00", False), ("wash", "05:00", "08:00", False)}

    role_hours = allocate_role_hours_by_day([entry])[1]
    assert role_hours["sort"] == 3.0 and role_hours["wash"] == 3.0
    totals = compute_schedule_totals([entry], {10: {"default_hourly_rate": 20}})
    assert totals["employee_totals"][10]["total_hours"] == 6.0
    assert totals["day_totals"][1]["total_hours"] == 6.0


def test_role_time_range_must_fit_shift_and_supports_overnight():
    cursor = _FakeCursor()
    _, err = _create(
        cursor,
        {
            "user_id": 10,
            "day_of_week": 1,
            "start_time": "09:00",
            "end_time": "12:00",
            "assignments": [{"role": "fold", "start_time": "11:00", "end_time": "13:00"}],
        },
    )
    assert err and "within the shift" in err

    entry, err = _create(
        cursor,
        {
            "user_id": 10,
            "day_of_week": 1,
            "start_time": "22:00",
            "end_time": "06:00",
            "assignments": [
                {"role": "fold", "full_shift": True},
                {"role": "dry", "start_time": "01:00", "end_time": "02:00"},
            ],
        },
    )
    assert err is None
    assert entry["hours"] == 8.0
    dry = next(a for a in entry["assignments"] if a["role"] == "dry")
    assert (dry["start_time"], dry["end_time"], dry["full_shift"]) == ("01:00", "02:00", False)


def test_remarks_only_kept_for_roles_with_remarks_enabled():
    cursor = _FakeCursor()
    update_role(cursor, 1, "weigher", {"remarks_enabled": True})
    entry, err = _create(
        cursor,
        {
            "user_id": 10,
            "day_of_week": 2,
            "start_time": "09:00",
            "end_time": "17:00",
            "assignments": [
                {"role": "fold", "remarks": "ignored"},
                {"role": "weigher", "start_time": "16:00", "end_time": "17:00", "remarks": "Scale 2"},
            ],
        },
    )
    assert err is None
    by_role = {a["role"]: a for a in entry["assignments"]}
    assert by_role["fold"]["remarks"] is None
    assert by_role["weigher"]["remarks"] == "Scale 2"


def test_task_rejected_on_timed_shift():
    for task in ("self_service", "lint_cleaning", "washer_cleaning"):
        _, err = _create(
            _FakeCursor(),
            {"user_id": 10, "day_of_week": 0, "start_time": "09:00", "end_time": "12:00", "roles": [task]},
        )
        assert err and "is a task" in err


def test_deactivated_role_blocks_new_assignments_but_keeps_existing():
    cursor = _FakeCursor()
    entry, err = _create(
        cursor,
        {"user_id": 10, "day_of_week": 3, "start_time": "09:00", "end_time": "12:00", "roles": ["weigher"]},
    )
    assert err is None
    update_role(cursor, 1, "weigher", {"active": False})
    _, err = _create(
        cursor,
        {"user_id": 20, "day_of_week": 3, "start_time": "09:00", "end_time": "12:00", "roles": ["weigher"]},
    )
    assert err and "inactive" in err
    p1, p2 = _patched()
    with p1, p2:
        kept, err = update_entry(MagicMock(), cursor, 1, entry["id"], {"end_time": "13:00"})
    assert err is None
    assert kept["roles"] == ["weigher"] and kept["hours"] == 4.0


def test_deactivated_role_cannot_be_added_as_another_row_on_existing_shift():
    cursor = _FakeCursor()
    entry, err = _create(
        cursor,
        {
            "user_id": 10,
            "day_of_week": 3,
            "start_time": "09:00",
            "end_time": "13:00",
            "assignments": [
                {"role": "fold", "full_shift": True},
                {"role": "weigher", "start_time": "09:00", "end_time": "10:00"},
            ],
        },
    )
    assert err is None
    update_role(cursor, 1, "weigher", {"active": False})
    p1, p2 = _patched()
    with p1, p2:
        _, err = update_entry(
            MagicMock(),
            cursor,
            1,
            entry["id"],
            {
                "assignments": [
                    {"role": "fold", "full_shift": True},
                    {"role": "weigher", "start_time": "09:00", "end_time": "10:00"},
                    {"role": "weigher", "start_time": "11:00", "end_time": "12:00"},
                ],
            },
        )
        assert err and "inactive" in err
        kept, err = update_entry(
            MagicMock(),
            cursor,
            1,
            entry["id"],
            {
                "assignments": [
                    {"role": "fold", "full_shift": True},
                    {"role": "weigher", "start_time": "10:00", "end_time": "11:00"},
                ],
            },
        )
    assert err is None
    weigher = [a for a in kept["assignments"] if a["role"] == "weigher"]
    assert len(weigher) == 1 and weigher[0]["start_time"] == "10:00"


def test_update_without_roles_preserves_role_ranges_and_remarks():
    cursor = _FakeCursor()
    update_role(cursor, 1, "post_weigh", {"remarks_enabled": True})
    entry, _ = _create(
        cursor,
        {
            "user_id": 10,
            "day_of_week": 4,
            "start_time": "06:00",
            "end_time": "14:00",
            "assignments": [
                {"role": "wash", "full_shift": True},
                {"role": "post_weigh", "start_time": "13:00", "end_time": "14:00", "remarks": "Bank A"},
            ],
        },
    )
    p1, p2 = _patched()
    with p1, p2:
        moved, err = move_entry(MagicMock(), cursor, 1, entry["id"], user_id=20, day_of_week=5)
    assert err is None
    post = next(a for a in moved["assignments"] if a["role"] == "post_weigh")
    assert (post["start_time"], post["end_time"], post["remarks"]) == ("13:00", "14:00", "Bank A")


def test_daily_responsibility_has_no_hours_and_coexists_with_shift():
    cursor = _FakeCursor()
    conn = MagicMock()
    _create(cursor, {"user_id": 10, "day_of_week": 1, "start_time": "09:00", "end_time": "17:00", "roles": ["fold"]})
    p1, p2 = _patched()
    with p1, p2:
        item, err = create_responsibility(
            conn, cursor, 1, week_start=WEEK, data={"user_id": 10, "day_of_week": 1, "role": "self_service", "remarks": "Front counter"}
        )
        assert err is None
        assert item["remarks"] == "Front counter"
        _, dup_err = create_responsibility(
            conn, cursor, 1, week_start=WEEK, data={"user_id": 10, "day_of_week": 1, "role": "self_service"}
        )
        assert dup_err and "already has" in dup_err
        _, timed_err = create_responsibility(
            conn, cursor, 1, week_start=WEEK, data={"user_id": 10, "day_of_week": 1, "role": "fold"}
        )
        assert timed_err and "requires start and end" in timed_err
        updated, err = update_responsibility(conn, cursor, 1, item["id"], {"remarks": "Back counter"})
        assert err is None and updated["remarks"] == "Back counter"
        payload = build_week_payload(conn, cursor, 1, week_start=WEEK)
    assert [r["role"] for r in payload["daily_responsibilities"]] == ["self_service"]
    alice = next(e for e in payload["employees"] if e["user_id"] == 10)
    assert alice["total_hours"] == 8.0
    assert payload["totals"]["day_totals"][1]["total_hours"] == 8.0
    assert any(r["code"] == "self_service" for r in payload["role_catalog"])


def test_scheduled_hours_dedupe_overlapping_entries_same_employee_day():
    base = {"organization_id": 1, "week_start": WEEK, "user_id": 10, "day_of_week": 0}
    shift = serialize_entry({**base, "id": 1, "role": "fold", "start_time": time(2, 0), "end_time": time(8, 0), "break_minutes": 30})
    stacked = serialize_entry({**base, "id": 2, "role": "sort", "start_time": time(2, 0), "end_time": time(5, 0), "break_minutes": 0})
    later = serialize_entry({**base, "id": 3, "role": "fold", "start_time": time(9, 0), "end_time": time(11, 0), "break_minutes": 0})
    hours = scheduled_hours_by_user_day([shift, stacked, later])
    assert hours[(10, 0)] == 7.5  # (2:00-8:00 minus 30m break) + 9:00-11:00


def _shift(entry_id, start, end, break_minutes, *, user_id=10, day=0, role="fold"):
    return serialize_entry(
        {
            "id": entry_id,
            "organization_id": 1,
            "week_start": WEEK,
            "user_id": user_id,
            "day_of_week": day,
            "role": role,
            "start_time": start,
            "end_time": end,
            "break_minutes": break_minutes,
        }
    )


def test_scheduled_hours_separate_shifts_keep_each_break():
    morning = _shift(1, time(6, 0), time(10, 0), 15)
    evening = _shift(2, time(14, 0), time(20, 0), 30)
    adjacent = _shift(3, time(10, 0), time(14, 0), 15, day=1)
    adjacent_prev = _shift(4, time(6, 0), time(10, 0), 15, day=1)
    hours = scheduled_hours_by_user_day([morning, evening, adjacent, adjacent_prev])
    assert hours[(10, 0)] == 9.25  # 3.75 + 5.5: unchanged from summing entries
    assert hours[(10, 1)] == 7.5  # touching shifts are not merged; both breaks deducted


def test_scheduled_hours_overlapping_shifts_with_breaks_count_once():
    first = _shift(1, time(8, 0), time(14, 0), 30)
    second = _shift(2, time(12, 0), time(16, 0), 15)
    assert first["hours"] + second["hours"] == 9.25  # the old double-counted total
    assert scheduled_hours_by_user_day([first, second])[(10, 0)] == 7.5  # 8:00-16:00 minus 30m


def test_scheduled_hours_overnight_shifts():
    overnight = _shift(1, time(22, 0), time(6, 0), 30)
    inside = _shift(2, time(23, 0), time(3, 0), 0, role="sort")
    early = _shift(3, time(2, 0), time(6, 0), 0, day=1)
    late = _shift(4, time(22, 0), time(6, 0), 30, day=1)
    hours = scheduled_hours_by_user_day([overnight, inside, early, late])
    assert overnight["hours"] == 7.5
    assert hours[(10, 0)] == 7.5  # 23:00-03:00 sits inside the overnight shift
    assert hours[(10, 1)] == 11.5  # 02:00-06:00 and 22:00-06:00 do not overlap


def test_compute_schedule_totals_dedupes_overlap_hours_and_cost():
    entries = [
        _shift(1, time(8, 0), time(14, 0), 30),
        _shift(2, time(12, 0), time(16, 0), 15, role="sort"),
        _shift(3, time(9, 0), time(13, 0), 0, user_id=20),
    ]
    totals = compute_schedule_totals(entries, {10: {"default_hourly_rate": 20.0}, 20: {"default_hourly_rate": 20.0}})
    assert totals["employee_totals"][10]["total_hours"] == 7.5
    assert totals["employee_totals"][10]["estimated_cost"] == 150.0
    assert totals["day_totals"][0]["total_hours"] == 11.5
    assert totals["day_totals"][0]["employee_count"] == 2


def test_carry_forward_copies_role_ranges_and_responsibilities():
    cursor = _FakeCursor()
    conn = MagicMock()
    _create(
        cursor,
        {
            "user_id": 10,
            "day_of_week": 1,
            "start_time": "02:00",
            "end_time": "08:00",
            "assignments": [
                {"role": "sort", "start_time": "02:00", "end_time": "05:00"},
                {"role": "fold", "start_time": "05:00", "end_time": "08:00"},
            ],
        },
    )
    p1, p2 = _patched()
    with p1, p2:
        create_responsibility(conn, cursor, 1, week_start=WEEK, data={"user_id": 10, "day_of_week": 1, "role": "drop_off_customer"})
        with patch("backend.planned_weekly_schedule.schedulable_worker_user_ids", return_value={10, 20}):
            result = carry_forward_week_schedule(
                conn, cursor, 1, target_week_start=date(2026, 6, 21), source_week_start=WEEK
            )
        copied = list_week_entries(cursor, 1, week_start=date(2026, 6, 21))
    assert result["responsibilities_copied"] == 1
    assert {(a["role"], a["start_time"]) for a in copied[0]["assignments"]} == {("sort", "02:00"), ("fold", "05:00")}
    assert any(r["week_start"] == date(2026, 6, 21) for r in cursor.responsibilities)


# --- Rinse default category, roles vs tasks, template propagation ----------------------------------

from backend.weekly_schedule_template import (  # noqa: E402
    copy_to_selected_weeks,
    disable_template,
    enable_template,
    ensure_cleaning_tasks_migrated,
    list_future_weeks,
    propagate_template_if_source,
    schedule_template_payload,
)


def test_new_shift_defaults_to_rinse_when_worker_allows_it():
    workers = [
        {"user_id": 10, "display_name": "Shared", "can_work_rinse": 1, "can_work_drop_off": 1, "can_work_both": 1},
        {"user_id": 20, "display_name": "VeeWash only", "business_entity": "veewash"},
    ]
    cursor = _FakeCursor()
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=workers
    ), patch("backend.payroll_employer_affiliation._organization_slug", return_value="veewash"):
        shared, err = create_entry(
            MagicMock(), cursor, 3, week_start=WEEK,
            data={"user_id": 10, "day_of_week": 1, "role": "fold", "start_time": "09:00", "end_time": "12:00"},
        )
        assert err is None
        own, err = create_entry(
            MagicMock(), cursor, 3, week_start=WEEK,
            data={"user_id": 20, "day_of_week": 1, "role": "fold", "start_time": "09:00", "end_time": "12:00"},
        )
        assert err is None
        explicit, err = create_entry(
            MagicMock(), cursor, 3, week_start=WEEK,
            data={
                "user_id": 10, "day_of_week": 2, "role": "fold", "start_time": "09:00", "end_time": "12:00",
                "employer_affiliation": "veewash",
            },
        )
    assert shared["employer_affiliation"] == "rinse_exclusive"
    assert own["employer_affiliation"] == "veewash"
    assert explicit["employer_affiliation"] == "veewash"


def test_copy_keeps_org_specific_category():
    cursor = _FakeCursor()
    cursor.rows.append(
        {
            "id": 1, "organization_id": 3, "week_start": WEEK, "user_id": 10, "day_of_week": 1, "role": "fold",
            "start_time": time(9, 0), "end_time": time(12, 0), "break_minutes": 0, "employer_affiliation": "veewash",
        }
    )
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True), patch(
        "backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()
    ), patch("backend.payroll_employer_affiliation._organization_slug", return_value="veewash"):
        carry_forward_week_schedule(MagicMock(), cursor, 3, target_week_start=date(2026, 6, 21), source_week_start=WEEK)
    assert [r["employer_affiliation"] for r in cursor.rows if r["week_start"] == date(2026, 6, 21)] == ["veewash"]


def test_new_role_defaults_to_rinse_group_and_kind_task_drops_times():
    cursor = _FakeCursor()
    role, err = create_role(cursor, 1, {"name": "Bagging"})
    assert err is None
    assert role["role_group"] == "RINSE_WF" and role["kind"] == "role" and role["uses_time_slots"] is True
    task, err = create_role(cursor, 1, {"name": "Restock Soap", "kind": "task"})
    assert err is None
    assert task["kind"] == "task" and task["uses_time_slots"] is False and task["remarks_enabled"] is True
    switched, err = update_role(cursor, 1, role["code"], {"kind": "task", "uses_time_slots": True})
    assert err is None and switched["kind"] == "task"
    _, err = create_role(cursor, 1, {"name": "Bad", "kind": "shift"})
    assert err and "kind" in err


def test_task_keeps_instructions_and_never_counts_hours():
    cursor = _FakeCursor()
    conn = MagicMock()
    _create(cursor, {"user_id": 10, "day_of_week": 1, "start_time": "09:00", "end_time": "17:00", "roles": ["fold"]})
    p1, p2 = _patched()
    with p1, p2:
        item, err = create_responsibility(
            conn, cursor, 1, week_start=WEEK,
            data={"user_id": 10, "day_of_week": 1, "role": "lint_cleaning", "remarks": "Before the break"},
        )
        assert err is None and item["remarks"] == "Before the break"
        payload = build_week_payload(conn, cursor, 1, week_start=WEEK)
    assert payload["employees"][0]["total_hours"] == 8.0
    assert payload["schedule_template"]["enabled"] is False


def test_cleaning_on_shifts_migrates_to_tasks_once_with_times_in_instructions():
    cursor = _FakeCursor()
    base = {"organization_id": 1, "week_start": WEEK, "break_minutes": 0, "employer_affiliation": None}
    cursor.rows = [
        {
            **base, "id": 1, "user_id": 10, "day_of_week": 0, "role": "lint_cleaning",
            "start_time": time(9, 0), "end_time": time(16, 0),
            "role_assignments": '[{"role":"lint_cleaning","remarks":"Before starting the break"}]',
        },
        {
            **base, "id": 2, "user_id": 20, "day_of_week": 1, "role": "fold,floor_cleaning",
            "start_time": time(8, 0), "end_time": time(14, 0),
            "role_assignments": '[{"role":"floor_cleaning","start_time":"13:00","end_time":"14:00"}]',
        },
        {**base, "id": 3, "user_id": 20, "day_of_week": 2, "role": "fold", "start_time": time(8, 0), "end_time": time(14, 0)},
    ]
    with patch("backend.planned_weekly_schedule.table_exists", return_value=True):
        result = ensure_cleaning_tasks_migrated(cursor, 1)
        assert ensure_cleaning_tasks_migrated(cursor, 1) is None
    assert [m["entry_id"] for m in result["moved"]] == [1, 2]
    assert [r["id"] for r in cursor.rows] == [1, 2, 3]
    lint_shift = cursor.rows[0]
    assert lint_shift["role"] == "" and lint_shift["role_assignments"] is None
    assert (lint_shift["start_time"], lint_shift["end_time"]) == (time(9, 0), time(16, 0))
    assert cursor.rows[1]["role"] == "fold" and cursor.rows[1]["role_assignments"] is None
    tasks = {(t["user_id"], t["day_of_week"], t["role"]): t["remarks"] for t in cursor.responsibilities}
    assert tasks == {
        (10, 0, "lint_cleaning"): "Before starting the break · Previously scheduled 9:00 AM – 4:00 PM",
        (20, 1, "floor_cleaning"): "Previously scheduled 1:00 PM – 2:00 PM",
    }


def test_task_conversion_keeps_shift_hours_and_is_safe_to_rerun():
    from backend.planned_weekly_schedule_responsibilities import migrate_timed_tasks_to_responsibilities

    cursor = _FakeCursor()
    base = {"organization_id": 1, "employer_affiliation": "rinse_exclusive", "day_of_week": 0, "user_id": 10}
    cursor.rows = [
        {
            **base, "id": 1, "week_start": WEEK, "role": "lint_cleaning", "break_minutes": 30,
            "start_time": time(9, 0), "end_time": time(16, 0),
            "role_assignments": '[{"role":"lint_cleaning","remarks":"Before starting the break"}]',
        },
        {
            **base, "id": 2, "week_start": WEEK - timedelta(days=7), "role": "lint_cleaning", "break_minutes": 0,
            "start_time": time(9, 0), "end_time": time(16, 0), "role_assignments": None,
        },
    ]
    p1, p2 = _patched()
    with p1, p2:
        first = migrate_timed_tasks_to_responsibilities(cursor, 1, task_roles={"lint_cleaning"}, from_week=WEEK)
        cursor.responsibilities[0]["remarks"] = "Edited by the manager"
        again = migrate_timed_tasks_to_responsibilities(cursor, 1, task_roles={"lint_cleaning"}, from_week=WEEK)
        payload = build_week_payload(MagicMock(), cursor, 1, week_start=WEEK)
    assert [m["entry_id"] for m in first["moved"]] == [1] and first["moved"][0]["shift_kept_without_role"]
    assert again["moved"] == []
    assert len(cursor.rows) == 2 and cursor.rows[1]["role"] == "lint_cleaning"
    assert [t["remarks"] for t in cursor.responsibilities] == ["Edited by the manager"]
    entry = payload["entries"][0]
    assert entry["role"] == "" and entry["roles"] == [] and entry["assignments"] == []
    assert entry["hours"] == 6.5
    assert payload["employees"][0]["total_hours"] == 6.5


def test_shift_can_be_saved_without_a_production_role():
    from backend.planned_weekly_schedule import _validate_entry_payload

    payload, err = _validate_entry_payload(
        {"user_id": 10, "day_of_week": 0, "start_time": "09:00", "end_time": "16:00", "assignments": []}
    )
    assert err is None and payload["role"] == "" and payload["role_assignments"] is None
    _, err = _validate_entry_payload({"user_id": 10, "day_of_week": 0, "start_time": "09:00", "end_time": "16:00"})
    assert err == "at least one role is required"


def _template_patches(current_week=WEEK):
    return (
        patch("backend.planned_weekly_schedule.table_exists", return_value=True),
        patch("backend.planned_weekly_schedule._load_workers", return_value=_mock_workers()),
        patch("backend.weekly_schedule_template.current_week_start", return_value=current_week),
    )


def _row(entry_id, week, user_id, day, role="fold", start=time(9, 0), end=time(12, 0), brk=0):
    return {
        "id": entry_id, "organization_id": 1, "week_start": week, "user_id": user_id, "day_of_week": day,
        "role": role, "start_time": start, "end_time": end, "break_minutes": brk, "employer_affiliation": None,
    }


def test_template_replaces_existing_future_weeks_and_propagates_changes():
    w1, w2, w3, past = WEEK, date(2026, 6, 21), date(2026, 6, 28), date(2026, 6, 7)
    cursor = _FakeCursor()
    cursor._id = 10
    cursor.rows = [
        _row(1, w1, 10, 1, brk=15),
        _row(2, w1, 10, 6, role="sort"),
        _row(3, w3, 20, 3, role="wash"),
        _row(4, past, 20, 2, role="wash"),
    ]
    cursor.responsibilities = [
        {"id": 1, "organization_id": 1, "week_start": w1, "user_id": 20, "day_of_week": 2, "role": "lint_cleaning", "remarks": "Dryers"}
    ]
    cursor._resp_id = 1
    conn = MagicMock()
    a, b, c = _template_patches()
    with a, b, c:
        result, err = enable_template(conn, cursor, 1, source_week_start=w1, user_id=7)
        assert err is None
        assert [(w["week_start"], w["status"]) for w in result["weeks"]] == [(str(w3), "replaced")]
        w3_rows = sorted((r["day_of_week"], r["role"], r["break_minutes"]) for r in cursor.rows if r["week_start"] == w3)
        # Exact weekday copy: Saturday stays Saturday, no Sunday seeding.
        assert w3_rows == [(1, "fold", 15), (6, "sort", 0)]
        assert [r for r in cursor.rows if r["week_start"] == past][0]["role"] == "wash"
        assert schedule_template_payload(cursor, 1, w3)["follows_template"] is True
        assert schedule_template_payload(cursor, 1, w1)["is_source"] is True

        # A later week opened for the first time inherits the template.
        from backend.planned_weekly_schedule import ensure_week_schedule_carried_forward

        carry = ensure_week_schedule_carried_forward(conn, cursor, 1, week_start=w2)
        assert carry["source_week_start"] == str(w1)

        # Deleting a source shift propagates to every later week.
        cursor.rows = [r for r in cursor.rows if not (r["week_start"] == w1 and r["day_of_week"] == 6)]
        sync = propagate_template_if_source(conn, cursor, 1, w1)
        assert {w["week_start"] for w in sync["weeks"]} == {str(w2), str(w3)}
        for week in (w2, w3):
            assert [(r["day_of_week"], r["role"]) for r in cursor.rows if r["week_start"] == week] == [(1, "fold")]
            assert [(t["day_of_week"], t["remarks"]) for t in cursor.responsibilities if t["week_start"] == week] == [(2, "Dryers")]
        # Changes to non-source weeks do not propagate.
        assert propagate_template_if_source(conn, cursor, 1, w2) is None

        disable_template(cursor, 1, user_id=7)
        assert propagate_template_if_source(conn, cursor, 1, w1) is None
        assert schedule_template_payload(cursor, 1, w3)["enabled"] is False


def test_template_source_cannot_be_a_past_week():
    cursor = _FakeCursor()
    cursor.rows = [_row(1, WEEK, 10, 1)]
    a, b, c = _template_patches(current_week=date(2026, 6, 21))
    with a, b, c:
        _, err = enable_template(MagicMock(), cursor, 1, source_week_start=WEEK, user_id=7)
    assert err and "current week" in err


def test_selected_weeks_copy_once_and_stop_template():
    w1, w2, w3, w4 = WEEK, date(2026, 6, 21), date(2026, 6, 28), date(2026, 7, 5)
    cursor = _FakeCursor()
    cursor._id = 10
    cursor.rows = [_row(1, w1, 10, 1), _row(2, w2, 20, 4, role="wash"), _row(3, w4, 20, 5, role="wash")]
    conn = MagicMock()
    a, b, c = _template_patches()
    with a, b, c:
        enable_template(conn, cursor, 1, source_week_start=w1, user_id=7)
        _, err = copy_to_selected_weeks(conn, cursor, 1, source_week_start=w2, target_weeks=[str(w1)], user_id=7)
        assert err and "not a future week" in err
        cursor.rows.append(_row(20, w2, 20, 3, role="sort"))
        result, err = copy_to_selected_weeks(
            conn, cursor, 1, source_week_start=w2, target_weeks=[str(w3), str(w3)], user_id=7
        )
        assert err is None
        assert result["template_stopped"] == str(w1)
        assert [(w["week_start"], w["status"]) for w in result["weeks"]] == [(str(w3), "created")]
        assert sorted(r["role"] for r in cursor.rows if r["week_start"] == w3) == ["fold", "sort"]
        # w4 was not selected, so it keeps what the earlier template sync wrote.
        assert [r["role"] for r in cursor.rows if r["week_start"] == w4] == ["fold"]
        assert propagate_template_if_source(conn, cursor, 1, w1) is None
        weeks = list_future_weeks(cursor, 1, source_week_start=w2)
    assert weeks[0]["week_start"] == str(w3) and weeks[0]["shifts"] == 2
    assert all(w["week_start"] > str(w2) for w in weeks)


# --- Operational groups and tasks saved with a shift ------------------------------------------------

from backend.planned_weekly_schedule_responsibilities import sync_day_tasks  # noqa: E402
from backend.weekly_schedule_roles import (  # noqa: E402
    create_role_group,
    list_role_groups,
    reorder_role_groups,
    update_role_group,
)


def test_groups_create_rename_reorder_deactivate_keep_role_assignments():
    cursor = _FakeCursor()
    group, err = create_role_group(cursor, 1, {"label": "Back Room"})
    assert err is None and group["code"] == "G_BACK_ROOM" and group["active"] is True
    _, err = create_role_group(cursor, 1, {"label": "back room"})
    assert err and "already exists" in err
    role, err = create_role(cursor, 1, {"name": "Bagging", "role_group": "G_BACK_ROOM"})
    assert err is None and role["role_group"] == "G_BACK_ROOM"

    renamed, err = update_role_group(cursor, 1, "G_BACK_ROOM", {"label": "Prep Area", "active": False})
    assert err is None and renamed["label"] == "Prep Area" and renamed["active"] is False
    catalog = {r["code"]: r for r in list_role_catalog(cursor, 1)}
    assert catalog[role["code"]]["role_group"] == "G_BACK_ROOM"
    kept, err = update_role(cursor, 1, role["code"], {"name": "Bagging 2", "role_group": "G_BACK_ROOM"})
    assert err is None and kept["role_group"] == "G_BACK_ROOM"
    _, err = create_role(cursor, 1, {"name": "Tagging", "role_group": "G_BACK_ROOM"})
    assert err == "Prep Area is an inactive group"
    _, err = create_role(cursor, 1, {"name": "Tagging", "role_group": "NOPE"})
    assert err == "unknown group: NOPE"

    assert reorder_role_groups(cursor, 1, ["G_BACK_ROOM", "CLEANING"]) is None
    codes = [g["code"] for g in list_role_groups(cursor, 1)]
    assert codes[:2] == ["G_BACK_ROOM", "CLEANING"] and "RINSE_WF" in codes
    assert reorder_role_groups(cursor, 1, ["MISSING"]) is not None


def test_shift_dialog_tasks_replace_day_tasks_without_touching_the_shift():
    cursor = _FakeCursor()
    entry, err = _create(
        cursor,
        {"user_id": 10, "day_of_week": 1, "start_time": "08:00", "end_time": "14:00", "break_minutes": 30, "roles": ["fold"]},
    )
    assert err is None
    shift_before = dict(cursor.rows[0])
    p1, p2 = _patched()
    with p1, p2:
        counts, err = sync_day_tasks(
            cursor, 1, week_start=WEEK, user_id=10, day_of_week=1,
            tasks=[{"role": "lint_cleaning", "remarks": "Dryers 1-6"}, {"role": "self_service"}],
        )
        assert err is None and counts == {"added": 2, "updated": 0, "removed": 0}
        counts, err = sync_day_tasks(
            cursor, 1, week_start=WEEK, user_id=10, day_of_week=1,
            tasks=[{"role": "lint_cleaning", "remarks": "Dryers 7-12"}],
        )
        assert err is None and counts == {"added": 0, "updated": 1, "removed": 1}
        _, err = sync_day_tasks(
            cursor, 1, week_start=WEEK, user_id=10, day_of_week=1,
            tasks=[{"role": "lint_cleaning"}, {"role": "lint_cleaning"}],
        )
        assert err == "Lint Cleaning is listed more than once"
        _, err = sync_day_tasks(cursor, 1, week_start=WEEK, user_id=10, day_of_week=1, tasks=[{"role": "fold"}])
        assert err and "is a role" in err
        payload = build_week_payload(MagicMock(), cursor, 1, week_start=WEEK)
    assert [(t["role"], t["remarks"]) for t in cursor.responsibilities] == [("lint_cleaning", "Dryers 7-12")]
    assert cursor.rows[0] == shift_before
    assert payload["employees"][0]["total_hours"] == 5.5


# --- Planned break slots -------------------------------------------------------------------------

from backend.planned_weekly_schedule import (  # noqa: E402
    _entry_copy_payload,
    _validate_breaks,
    apply_week_copy,
    entry_break_breakdown,
    scheduled_hours_breakdown_by_user_day,
)


def _break_row(entry_id, user_id, start, end, roles="fold", *, break_minutes=0, slots=None, day=1, assignments=None):
    import json

    row = {
        "id": entry_id,
        "organization_id": 1,
        "week_start": date(2026, 6, 14),
        "user_id": user_id,
        "day_of_week": day,
        "role": roles,
        "start_time": start,
        "end_time": end,
        "break_minutes": break_minutes,
        "break_slots": json.dumps(slots) if slots is not None else None,
    }
    if assignments is not None:
        row["role_assignments"] = json.dumps(assignments)
    return serialize_entry(row)


def _slots(*pairs):
    return [{"start_time": a, "end_time": b} for a, b in pairs]


def test_break_validation_inside_shift_overnight_and_overlap():
    ok, err = _validate_breaks(
        {"break_slots": _slots(("12:00", "12:30"), ("15:00", "15:15"))}, shift_start=time(9, 0), shift_end=time(17, 0)
    )
    assert err is None and ok["break_minutes"] == 45
    ok, err = _validate_breaks(
        {"break_slots": _slots(("01:00", "01:30"), ("23:30", "23:45"))}, shift_start=time(22, 0), shift_end=time(6, 0)
    )
    assert err is None
    assert [s["start_time"] for s in __import__("json").loads(ok["break_slots"])] == ["23:30", "01:00"]

    for slots, shift in (
        (_slots(("16:45", "17:15")), (time(9, 0), time(17, 0))),
        (_slots(("08:00", "08:30")), (time(9, 0), time(17, 0))),
        (_slots(("05:45", "06:15")), (time(22, 0), time(6, 0))),
        (_slots(("21:00", "21:30")), (time(22, 0), time(6, 0))),
    ):
        _, err = _validate_breaks({"break_slots": slots}, shift_start=shift[0], shift_end=shift[1])
        assert err and "within the shift" in err

    _, err = _validate_breaks(
        {"break_slots": _slots(("12:00", "12:30"), ("12:15", "12:45"))}, shift_start=time(9, 0), shift_end=time(17, 0)
    )
    assert err and "overlaps" in err
    _, err = _validate_breaks({"break_slots": _slots(("12:00", "12:00"))}, shift_start=time(9, 0), shift_end=time(17, 0))
    assert err


def test_timed_break_replaces_duration_only_deduction():
    # A legacy 30-minute break given a time keeps one 30-minute deduction.
    ok, _ = _validate_breaks(
        {"break_minutes": 30, "break_slots": _slots(("12:00", "12:30"))}, shift_start=time(9, 0), shift_end=time(17, 0)
    )
    assert ok["break_minutes"] == 30
    # The dialog sends the untimed remainder explicitly.
    ok, _ = _validate_breaks(
        {"break_minutes": 45, "unscheduled_break_minutes": 15, "break_slots": _slots(("12:00", "12:30"))},
        shift_start=time(9, 0),
        shift_end=time(17, 0),
    )
    assert ok["break_minutes"] == 45
    legacy = _break_row(1, 10, time(9, 0), time(17, 0), break_minutes=30)
    assert entry_break_breakdown(legacy) == {
        "gross_minutes": 480,
        "break_minutes": 30,
        "timed_break_minutes": 0,
        "unscheduled_break_minutes": 30,
    }
    assert legacy["hours"] == 7.5 and legacy["break_slots"] == []
    timed = _break_row(2, 10, time(9, 0), time(17, 0), break_minutes=30, slots=_slots(("12:00", "12:30")))
    assert timed["hours"] == 7.5 and timed["unscheduled_break_minutes"] == 0 and timed["timed_break_minutes"] == 30


def test_breaks_multiple_partial_overnight_and_overlapping_shifts_count_once():
    multi = _break_row(1, 10, time(9, 0), time(17, 0), break_minutes=45, slots=_slots(("11:50", "12:20"), ("15:00", "15:15")))
    assert multi["hours"] == 7.25 and multi["gross_hours"] == 8.0
    overnight = _break_row(2, 11, time(22, 0), time(6, 0), "sort", break_minutes=30, slots=_slots(("01:00", "01:30")))
    assert overnight["hours"] == 7.5
    a = _break_row(3, 12, time(8, 0), time(14, 0), "wash", break_minutes=30, slots=_slots(("12:00", "12:30")))
    b = _break_row(4, 12, time(12, 0), time(16, 0), "fold", break_minutes=30, slots=_slots(("12:00", "12:30")))
    parts = scheduled_hours_breakdown_by_user_day([multi, overnight, a, b])
    assert parts[(12, 1)] == {
        "gross_hours": 8.0,
        "break_hours": 0.5,
        "timed_break_hours": 0.5,
        "unscheduled_break_hours": 0.0,
        "net_hours": 7.5,
    }
    totals = compute_schedule_totals([multi, overnight, a, b], {})
    assert totals["day_totals"][1]["total_hours"] == 22.25
    assert totals["day_totals"][1]["gross_hours"] == 24.0
    assert totals["day_totals"][1]["break_hours"] == 1.75
    assert totals["employee_totals"][12]["total_hours"] == 7.5


def test_role_hours_remove_timed_breaks_before_splitting_and_share_untimed_breaks():
    both = _break_row(
        1,
        10,
        time(8, 0),
        time(12, 0),
        "wash,fold",
        break_minutes=30,
        slots=_slots(("10:00", "10:30")),
    )
    hours = allocate_role_hours_by_day([both])[1]
    assert hours["wash"] == 1.75 and hours["fold"] == 1.75
    legacy = _break_row(2, 11, time(9, 0), time(17, 0), "sort", break_minutes=30)
    # A break without a time comes off the role hours as a share, so role hours are net.
    assert allocate_role_hours_by_day([legacy])[1]["sort"] == 7.5
    totals = compute_schedule_totals([both, legacy], {})
    assert totals["day_totals"][1]["total_hours"] == 11.0
    assert totals["day_totals"][1]["unscheduled_break_hours"] == 0.5
    day_roles = sum(row["hours"] for row in totals["day_totals"][1]["roles"])
    assert day_roles == totals["day_totals"][1]["total_hours"]


def _role_selection_fixture():
    a = _break_row(11, 1, time(8, 0), time(16, 0), "fold", break_minutes=30, slots=_slots(("12:00", "12:30")))
    b = _break_row(21, 2, time(8, 0), time(12, 0), "wash,fold")
    c1 = _break_row(31, 3, time(6, 0), time(14, 0), "wash")
    c2 = _break_row(32, 3, time(12, 0), time(16, 0), "fold")
    d = _break_row(41, 4, time(22, 0), time(6, 0), "sort", break_minutes=30)
    e = _break_row(
        51,
        5,
        time(9, 0),
        time(13, 0),
        "fold,sort",
        break_minutes=30,
        assignments=[
            {"role": "fold", "start_time": "09:00", "end_time": "11:00"},
            {"role": "sort", "start_time": "11:00", "end_time": "13:00"},
        ],
    )
    return [a, b, c1, c2, d, e]


def test_day_role_totals_count_distinct_people_and_net_hours_like_the_frontend():
    entries = _role_selection_fixture()
    totals = compute_schedule_totals(entries, {})
    mon = totals["day_totals"][1]
    roles = {row["role"]: (row["employees"], row["hours"], row["unallocated_break_hours"]) for row in mon["roles"]}
    # Same fixture as weeklyScheduleRoleSelection.test.js. The overnight single-role sort shift's untimed
    # 30 min comes off sort; the fold+sort shift's untimed 30 min stays unallocated (gross in both roles).
    assert roles == {"wash": (2, 9.0, 0.0), "sort": (2, 9.5, 0.5), "fold": (4, 14.5, 0.5)}
    assert mon["unallocated_break_hours"] == 0.5
    assert mon["fold_count"] == 4 and mon["wash_count"] == 2 and mon["folder_count"] == 4
    assert mon["fold_hours"] == 14.5 and mon["sort_hours"] == 9.5
    assert round(sum(hours for _, hours, _ in roles.values()) - mon["unallocated_break_hours"], 2) == mon["total_hours"]


def test_day_role_counts_are_people_not_assignments():
    shifts = [
        _break_row(1, 1, time(8, 0), time(10, 0), "fold"),
        _break_row(2, 1, time(11, 0), time(13, 0), "fold"),
        _break_row(3, 1, time(14, 0), time(16, 0), "fold"),
        _break_row(4, 2, time(8, 0), time(12, 0), "fold"),
    ]
    mon = compute_schedule_totals(shifts, {})["day_totals"][1]
    assert mon["fold_count"] == 2
    assert mon["roles"] == [{"role": "fold", "employees": 2, "hours": 10.0, "unallocated_break_hours": 0.0}]


def test_hidden_simultaneous_role_keeps_its_share():
    from backend.planned_weekly_schedule import employee_day_timeline, timeline_role_breakdown

    c1 = _break_row(31, 3, time(6, 0), time(14, 0), "wash")
    c2 = _break_row(32, 3, time(12, 0), time(16, 0), "fold")
    breakdown = timeline_role_breakdown(employee_day_timeline([c1, c2]))
    assert breakdown["fold"]["net"] == 3.0 and breakdown["wash"]["net"] == 7.0
    overnight = _break_row(41, 4, time(22, 0), time(6, 0), "sort", break_minutes=30)
    parts = timeline_role_breakdown(employee_day_timeline([overnight]))["sort"]
    assert parts == {
        "gross": 8.0,
        "worked": 8.0,
        "timed_break": 0.0,
        "untimed_break": 0.5,
        "unallocated_break": 0.0,
        "net": 7.5,
    }


def test_untimed_break_on_multi_role_shift_stays_unallocated_but_net_hours_include_it():
    from backend.planned_weekly_schedule import employee_day_timeline, timeline_role_breakdown

    single = _break_row(1, 1, time(8, 0), time(16, 0), "fold", break_minutes=30)
    single_day = employee_day_timeline([single])
    assert single_day["net_hours"] == 7.5
    assert timeline_role_breakdown(single_day)["fold"]["net"] == 7.5

    multi = _break_row(2, 2, time(8, 0), time(16, 0), "wash,fold", break_minutes=30)
    multi_day = employee_day_timeline([multi])
    assert multi_day["gross_hours"] == 8.0 and multi_day["net_hours"] == 7.5
    breakdown = timeline_role_breakdown(multi_day)
    for role in ("wash", "fold"):
        assert breakdown[role]["net"] == 4.0
        assert breakdown[role]["untimed_break"] == 0.0
        assert breakdown[role]["unallocated_break"] == 0.5
    mon = compute_schedule_totals([single, multi], {})["day_totals"][1]
    assert mon["total_hours"] == 15.0
    assert mon["unallocated_break_hours"] == 0.5
    assert {row["role"]: (row["hours"], row["unallocated_break_hours"]) for row in mon["roles"]} == {
        "wash": (4.0, 0.5),
        "fold": (11.5, 0.5),
    }


def test_create_update_and_copy_keep_break_slots_and_deletions():
    import json

    cursor = _FakeCursor()
    conn = MagicMock()
    week = date(2026, 6, 14)
    with patch("backend.planned_weekly_schedule._schedule_end_time_enabled", return_value=True), patch(
        "backend.payroll_employer_affiliation._organization_slug", return_value="veewash"
    ), patch("backend.planned_weekly_schedule._load_workers", return_value=[]):
        entry, err = create_entry(
            conn,
            cursor,
            1,
            week_start=week,
            data={
                "user_id": 10,
                "day_of_week": 1,
                "start_time": "22:00",
                "end_time": "06:00",
                "role": "fold",
                "break_minutes": 45,
                "unscheduled_break_minutes": 15,
                "break_slots": _slots(("01:00", "01:30")),
            },
        )
        assert err is None, err
        assert entry["break_slots"] == _slots(("01:00", "01:30"))
        assert entry["break_minutes"] == 45 and entry["unscheduled_break_minutes"] == 15 and entry["hours"] == 7.25

        _, err = update_entry(conn, cursor, 1, entry["id"], {"break_slots": _slots(("07:00", "07:30"))})
        assert err and "within the shift" in err

        next_week = week + timedelta(days=7)
        copy = {"entries": [_entry_copy_payload(entry, day_of_week=1)], "organization_slug": "veewash"}
        apply_week_copy(cursor, 1, target_week_start=next_week, copy=copy)
        copied = list_week_entries(cursor, 1, week_start=next_week)
        assert copied[0]["break_slots"] == _slots(("01:00", "01:30"))
        assert copied[0]["break_minutes"] == 45 and copied[0]["hours"] == 7.25

        updated, err = update_entry(
            conn, cursor, 1, entry["id"], {"break_slots": [], "unscheduled_break_minutes": 0, "break_minutes": 0}
        )
        assert err is None, err
        assert updated["break_slots"] == [] and updated["break_minutes"] == 0 and updated["hours"] == 8.0
        assert json.loads(cursor.rows[0]["break_slots"] or "[]") == []
