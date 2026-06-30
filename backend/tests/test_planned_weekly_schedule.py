"""Tests for planned weekly schedule totals, move, org isolation, and exclusions."""

from __future__ import annotations

from datetime import date, time
from unittest.mock import MagicMock, patch

from backend.planned_weekly_schedule import (
    build_week_payload,
    bulk_set_week_entry_employer_affiliation,
    carry_forward_week_schedule,
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
        self.connection = object()
        self._rowcount = 0

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split()).lower()
        params = params or ()
        if "show tables" in sql_norm or "information_schema" in sql_norm:
            self._last = [{"cnt": 1}]
            return
        if "create table" in sql_norm:
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
            }
            self.rows.append(row)
            return
        if "update planned_weekly_schedule_entries" in sql_norm:
            if "set employer_affiliation=%s" in sql_norm and "week_start=%s" in sql_norm:
                aff, org_id, week_start = params
                count = 0
                for row in self.rows:
                    if row["organization_id"] == org_id and row["week_start"] == week_start:
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
            entry_id = params[8] if len(params) > 8 else params[7]
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
                        }
                    )
            return
        if "delete from planned_weekly_schedule_entries" in sql_norm:
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
    assert normalize_weekly_role("sort") == "sort"
    assert parse_weekly_roles("wash,fold") == ["wash", "fold"]
    assert parse_weekly_roles("wash,weigher") == ["wash", "weigher"]
    assert roles_to_storage(["fold", "sort", "wash", "weigher"]) == "sort,wash,weigher,fold"


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


def test_bulk_set_week_entry_employer_affiliation_skips_cross_entity_worker():
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
    ):
        updated, err, skipped = bulk_set_week_entry_employer_affiliation(
            conn,
            cursor,
            1,
            week_start=week,
            employer_affiliation="rinse_exclusive",
        )
    assert err is None
    assert updated == 0
    assert len(skipped) == 1
    assert cursor.rows[0]["employer_affiliation"] == "washpro"
