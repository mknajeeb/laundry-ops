"""Tests for daily shift roster CRUD and labor summary (additive dashboard fields)."""

from __future__ import annotations

from datetime import date, time

from backend.daily_shift_labor_summary import build_labor_summary
from backend.daily_shift_roster import (
    batch_save_roster_entries,
    build_roster_payload,
    calc_cost,
    calc_hours,
    create_roster_entry,
    delete_roster_entry,
    list_roster_entries,
    normalize_role,
    parse_time_value,
    roster_entry_match_key,
    serialize_roster_entry_data,
    update_roster_entry,
)
from backend.daily_shift_roster_payroll import (
    import_payroll_records_into_roster,
    map_payroll_record_to_roster_data,
)


class _FakeCursor:
    def __init__(self):
        self._id = 0
        self.rows: list[dict] = []
        self.connection = object()

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split()).lower()
        params = params or ()
        if "show columns" in sql_norm:
            self._last = [{"Null": "YES"}]
            return
        if "create table" in sql_norm:
            return
        if "insert into daily_shift_roster_entries" in sql_norm:
            self._id += 1
            row = {
                "id": self._id,
                "organization_id": params[0],
                "roster_date": params[1],
                "employee_name": params[2],
                "role": params[3],
                "start_time": params[4],
                "end_time": params[5],
                "break_minutes": params[6],
                "rate": params[7],
                "notes": params[8],
                "excluded": params[9] if len(params) > 9 else 0,
            }
            self.rows.append(row)
            return
        if "update daily_shift_roster_entries" in sql_norm:
            entry_id = params[-1]
            for row in self.rows:
                if row["id"] == entry_id:
                    row.update(
                        {
                            "employee_name": params[0],
                            "role": params[1],
                            "start_time": params[2],
                            "end_time": params[3],
                            "break_minutes": params[4],
                            "rate": params[5],
                            "notes": params[6],
                            "excluded": params[7],
                        }
                    )
            return
        if "delete from daily_shift_roster_entries" in sql_norm:
            org_id, entry_id = params
            self.rows = [r for r in self.rows if not (r["organization_id"] == org_id and r["id"] == entry_id)]
            return
        if "from daily_shift_roster_entries" in sql_norm and "where organization_id" in sql_norm:
            if "and id =" in sql_norm:
                org_id, entry_id = params
                self._last = [r for r in self.rows if r["organization_id"] == org_id and r["id"] == entry_id]
            else:
                org_id, roster_date = params
                self._last = [
                    r
                    for r in self.rows
                    if r["organization_id"] == org_id and r["roster_date"] == roster_date
                ]
            return

    def fetchone(self):
        rows = getattr(self, "_last", [])
        return rows[0] if rows else None

    def fetchall(self):
        return list(getattr(self, "_last", []))

    @property
    def lastrowid(self):
        return self._id


def _patch_table_exists(monkeypatch):
    monkeypatch.setattr("backend.daily_shift_roster.table_exists", lambda *_a, **_k: True)


class TestRosterCalculations:
    def test_calc_hours_subtracts_break(self):
        assert calc_hours(time(8, 0), time(16, 0), 30) == 7.5

    def test_calc_hours_overnight_shift(self):
        assert calc_hours(time(22, 0), time(6, 0), 0) == 8.0

    def test_calc_cost(self):
        assert calc_cost(7.5, 18.5) == 138.75

    def test_parse_time_value(self):
        assert parse_time_value("08:30") == time(8, 30)
        assert parse_time_value("bad") is None

    def test_normalize_role(self):
        assert normalize_role("Folder") == "folder"
        assert normalize_role("OPERATOR") == "operator"
        assert normalize_role("invalid") is None


class TestRosterCrud:
    def test_create_list_update_delete(self, monkeypatch):
        _patch_table_exists(monkeypatch)
        cursor = _FakeCursor()
        org = 3
        roster_date = date(2026, 6, 18)

        entry, err = create_roster_entry(
            cursor,
            org,
            roster_date=roster_date,
            data={
                "employee_name": "Alice Worker",
                "role": "folder",
                "start_time": "08:00",
                "end_time": "16:00",
                "break_minutes": 30,
                "rate": 18.5,
                "notes": "Main floor",
            },
        )
        assert err is None
        assert entry["hours"] == 7.5
        assert entry["cost"] == 138.75

        entries = list_roster_entries(cursor, org, roster_date=roster_date)
        assert len(entries) == 1

        updated, err = update_roster_entry(
            cursor,
            org,
            entry["id"],
            {"break_minutes": 60, "rate": 19},
        )
        assert err is None
        assert updated["hours"] == 7.0
        assert updated["cost"] == 133.0

        ok, err = delete_roster_entry(cursor, org, entry["id"])
        assert ok is True
        assert list_roster_entries(cursor, org, roster_date=roster_date) == []


class TestOpenShiftEntries:
    def test_open_shift_has_no_hours_or_cost(self, monkeypatch):
        _patch_table_exists(monkeypatch)
        serialized = serialize_roster_entry_data(
            {
                "employee_name": "Alice Worker",
                "role": "folder",
                "start_time": "09:00",
                "end_time": None,
                "shift_open": True,
                "break_minutes": 0,
                "rate": 19.5,
            }
        )
        assert serialized["shift_open"] is True
        assert serialized["hours"] is None
        assert serialized["cost"] is None

    def test_create_open_shift_entry(self, monkeypatch):
        _patch_table_exists(monkeypatch)
        cursor = _FakeCursor()
        entry, err = create_roster_entry(
            cursor,
            3,
            roster_date=date(2026, 6, 18),
            data={
                "employee_name": "Bob Worker",
                "role": "folder",
                "start_time": "10:15",
                "shift_open": True,
                "end_time": None,
                "break_minutes": 0,
                "rate": 19.5,
            },
        )
        assert err is None
        assert entry["shift_open"] is True
        assert entry["end_time"] is None
        assert entry["hours"] is None
        assert entry["cost"] is None


class TestPayrollPrefillMapping:
    def test_map_completed_payroll_record(self):
        mapped = map_payroll_record_to_roster_data(
            {
                "id": 42,
                "worker_name": "Jane Doe",
                "status": "completed",
                "clock_in_at": "2026-06-18 08:30:00",
                "clock_out_at": "2026-06-18 16:00:00",
                "break_seconds": 1800,
                "hourly_rate": 20.0,
                "worker_category": "w2",
                "notes": "Floor",
            }
        )
        assert mapped["employee_name"] == "Jane Doe"
        assert mapped["start_time"] == "08:30"
        assert mapped["end_time"] == "16:00"
        assert mapped["break_minutes"] == 30
        assert mapped["shift_open"] is False
        assert mapped["rate"] == 20.0

    def test_map_open_payroll_record(self):
        mapped = map_payroll_record_to_roster_data(
            {
                "id": 43,
                "worker_name": "Sam Open",
                "status": "open",
                "clock_in_at": "2026-06-18 09:00:00",
                "clock_out_at": None,
                "break_seconds": 0,
                "hourly_rate": 0,
                "worker_category": "w2",
            }
        )
        assert mapped["shift_open"] is True
        assert mapped["end_time"] is None
        assert mapped["rate"] == 19.5

    def test_map_contractor_default_rate(self):
        mapped = map_payroll_record_to_roster_data(
            {
                "id": 44,
                "worker_name": "Contractor One",
                "status": "completed",
                "clock_in_at": "2026-06-18 07:00:00",
                "clock_out_at": "2026-06-18 15:00:00",
                "break_seconds": 0,
                "hourly_rate": None,
                "worker_category": "contractor_1099",
            }
        )
        assert mapped["rate"] == 17.0


class TestPayrollImport:
    def test_import_skips_duplicate_employee_clock_in(self, monkeypatch):
        _patch_table_exists(monkeypatch)
        cursor = _FakeCursor()
        org = 3
        roster_date = date(2026, 6, 18)

        payroll_rows = [
            {
                "id": 1,
                "worker_name": "Alice Worker",
                "status": "completed",
                "clock_in_at": "2026-06-18 08:00:00",
                "clock_out_at": "2026-06-18 16:00:00",
                "break_seconds": 0,
                "hourly_rate": 19.5,
                "worker_category": "w2",
            },
            {
                "id": 2,
                "worker_name": "Bob Worker",
                "status": "completed",
                "clock_in_at": "2026-06-18 09:00:00",
                "clock_out_at": "2026-06-18 17:00:00",
                "break_seconds": 0,
                "hourly_rate": 19.5,
                "worker_category": "w2",
            },
        ]

        monkeypatch.setattr(
            "backend.daily_shift_roster_payroll.list_payroll_time_records_for_date",
            lambda *_a, **_k: payroll_rows,
        )

        create_roster_entry(
            cursor,
            org,
            roster_date=roster_date,
            data={
                "employee_name": "Alice Worker",
                "role": "folder",
                "start_time": "08:00",
                "end_time": "16:00",
                "break_minutes": 0,
                "rate": 19.5,
            },
        )

        added, saved, err = import_payroll_records_into_roster(
            cursor, org, roster_date=roster_date, conn=object()
        )
        assert err is None
        assert added == 1
        assert len(saved) == 2
        names = {e["employee_name"] for e in saved}
        assert names == {"Alice Worker", "Bob Worker"}

    def test_roster_entry_match_key_normalizes_name(self):
        assert roster_entry_match_key(" Alice ", "08:00") == ("alice", "08:00")


class TestRosterPayloadMessages:
    def test_payroll_found_message_when_no_roster(self, monkeypatch):
        _patch_table_exists(monkeypatch)
        cursor = _FakeCursor()
        monkeypatch.setattr(
            "backend.daily_shift_roster_payroll.build_payroll_prefill_entries",
            lambda *_a, **_k: [{"employee_name": "Jane", "start_time": "08:00"}],
        )
        payload = build_roster_payload(
            cursor, 3, roster_date=date(2026, 6, 18), conn=object()
        )
        assert payload["has_roster"] is False
        assert payload["payroll_record_count"] == 1
        assert payload["message"] == "Payroll records found. Review and save today's roster."
        assert len(payload["payroll_prefill"]) == 1

    def test_empty_message_when_no_roster_or_payroll(self, monkeypatch):
        _patch_table_exists(monkeypatch)
        cursor = _FakeCursor()
        monkeypatch.setattr(
            "backend.daily_shift_roster_payroll.build_payroll_prefill_entries",
            lambda *_a, **_k: [],
        )
        payload = build_roster_payload(
            cursor, 3, roster_date=date(2026, 6, 18), conn=object()
        )
        assert payload["message"] == "No labor roster recorded for this date."
        assert payload["payroll_prefill"] == []


class TestExcludedEntries:
    def test_excluded_entry_omitted_from_roster_summary(self, monkeypatch):
        _patch_table_exists(monkeypatch)
        cursor = _FakeCursor()
        org = 3
        roster_date = date(2026, 6, 18)

        create_roster_entry(
            cursor,
            org,
            roster_date=roster_date,
            data={
                "employee_name": "Included Worker",
                "role": "folder",
                "start_time": "08:00",
                "end_time": "16:00",
                "break_minutes": 0,
                "rate": 20.0,
            },
        )
        create_roster_entry(
            cursor,
            org,
            roster_date=roster_date,
            data={
                "employee_name": "Excluded Worker",
                "role": "folder",
                "start_time": "09:00",
                "end_time": "17:00",
                "break_minutes": 0,
                "rate": 20.0,
                "excluded": True,
            },
        )

        monkeypatch.setattr(
            "backend.daily_shift_roster_payroll.build_payroll_prefill_entries",
            lambda *_a, **_k: [],
        )
        payload = build_roster_payload(cursor, org, roster_date=roster_date, conn=None)
        assert payload["summary"]["employee_count"] == 1
        assert payload["summary"]["total_hours"] == 8.0
        assert payload["summary"]["total_cost"] == 160.0
        assert len(payload["entries"]) == 2

    def test_excluded_entry_omitted_from_labor_summary(self):
        roster = [
            {
                "employee_name": "Included Worker",
                "role": "folder",
                "hours": 8.0,
                "cost": 160.0,
                "rate": 20.0,
            },
            {
                "employee_name": "Excluded Worker",
                "role": "folder",
                "hours": 8.0,
                "cost": 160.0,
                "rate": 20.0,
                "excluded": True,
            },
        ]
        summary = build_labor_summary(
            roster,
            productivity_section={"executive_summary": {"total_bags_completed": 10}},
        )
        assert summary["kpis"]["total_labor_hours"] == 8.0
        assert summary["kpis"]["total_labor_cost"] == 160.0
        assert len(summary["employee_details"]) == 1

    def test_batch_save_skips_excluded_drafts(self, monkeypatch):
        _patch_table_exists(monkeypatch)
        cursor = _FakeCursor()
        org = 3
        roster_date = date(2026, 6, 18)
        created, err = batch_save_roster_entries(
            cursor,
            org,
            roster_date=roster_date,
            entries=[
                {
                    "employee_name": "Alice Worker",
                    "role": "folder",
                    "start_time": "08:00",
                    "end_time": "16:00",
                    "break_minutes": 0,
                    "rate": 19.5,
                },
                {
                    "employee_name": "Bob Worker",
                    "role": "folder",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "break_minutes": 0,
                    "rate": 19.5,
                    "excluded": True,
                },
            ],
        )
        assert err is None
        assert len(created) == 1
        assert list_roster_entries(cursor, org, roster_date=roster_date)[0]["employee_name"] == "Alice Worker"


class TestLaborSummary:
    def test_no_roster_returns_unavailable(self):
        summary = build_labor_summary([], productivity_section={"executive_summary": {"total_bags_completed": 5}})
        assert summary["available"] is False
        assert summary["kpis"]["total_labor_hours"] is None
        assert summary["message"] == "No labor roster recorded for this date."

    def test_labor_summary_with_productivity(self):
        roster = [
            {
                "employee_name": "Alice Worker",
                "role": "folder",
                "hours": 8.0,
                "cost": 160.0,
                "rate": 20.0,
            },
            {
                "employee_name": "Bob Operator",
                "role": "operator",
                "hours": 6.0,
                "cost": 90.0,
                "rate": 15.0,
            },
        ]
        productivity = {
            "executive_summary": {
                "total_bags_completed": 40,
                "total_pounds_completed": 500.0,
            },
            "employees": [
                {"employee": "Alice Worker", "completed_bags": 30, "total_completed_lbs": 400.0},
                {"employee": "Bob Operator", "completed_bags": 0, "total_completed_lbs": 100.0},
            ],
        }
        summary = build_labor_summary(roster, productivity_section=productivity)
        assert summary["available"] is True
        assert summary["kpis"]["total_labor_hours"] == 14.0
        assert summary["kpis"]["folder_hours"] == 8.0
        assert summary["kpis"]["operator_hours"] == 6.0
        assert summary["kpis"]["total_labor_cost"] == 250.0
        assert summary["kpis"]["cost_per_bag"] == 6.25
        assert summary["kpis"]["cost_per_pound"] == 0.5
        assert summary["role_breakdown"]["folders"]["bags_completed"] == 30
        assert summary["role_breakdown"]["operators"]["pounds_processed"] == 100.0
        assert len(summary["employee_details"]) == 2


class TestEmployeeProductivityPayloadBackwardCompat:
    def test_labor_summary_additive_without_changing_productivity(self, monkeypatch):
        from backend.rinse_employee_completed_bags import build_employee_productivity_dashboard_payload

        scoped = {
            "employees": [{"employee": "Alice", "completed_bags": 2, "total_completed_lbs": 20.0}],
            "executive_summary": {
                "total_employees_active": 1,
                "total_bags_completed": 2,
                "total_pounds_completed": 20.0,
                "average_bags_per_hour": 1.5,
                "average_pounds_per_hour": 15.0,
            },
            "productivity_scope_label": "WF Only",
        }

        monkeypatch.setattr(
            "backend.rinse_at_vendor_module.build_at_vendor_module",
            lambda *_a, **_k: {"employee_completed_bags_today": scoped},
        )
        monkeypatch.setattr(
            "backend.rinse_employee_productivity_settings.include_hd_in_employee_productivity",
            lambda *_a, **_k: False,
        )
        monkeypatch.setattr(
            "backend.rinse_employee_productivity_presentation.apply_employee_productivity_scope",
            lambda section, **_k: scoped,
        )
        monkeypatch.setattr(
            "backend.daily_shift_roster.list_roster_entries",
            lambda *_a, **_k: [],
        )
        monkeypatch.setattr(
            "backend.rinse_simple_shift_performance._load_rinse_user_maps",
            lambda *_a, **_k: {},
        )

        payload = build_employee_productivity_dashboard_payload(
            object(),
            3,
            selected_date_et=date(2026, 6, 18),
        )
        assert payload["employee_completed_bags_today"]["executive_summary"]["total_bags_completed"] == 2
        assert payload["labor_summary"]["available"] is False
        assert "labor_summary" in payload
