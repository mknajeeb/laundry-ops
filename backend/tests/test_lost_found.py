"""Lost & Found rules, facility isolation, photos, and activity completion gate."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest
from flask import Flask

from backend.lost_found import (
    account_item,
    add_box_photo,
    add_item_photo,
    change_status,
    get_item,
    list_found_items,
    list_issue_employees,
    search_issue_reports,
    notify_found_item,
    reconciliation_view,
    report_found_item,
    snapshot_reconciliation_on_complete,
    veewash_issue_catalog,
)
from backend.lost_found_photos import read_found_item_image, save_found_item_image
from backend.lost_found_rules import (
    ACTIVITY_CODE,
    LostFoundError,
    reconciliation_blockers,
    require_configured_identifier,
    select_reconciliation_items,
    snapshot_is_current,
    validate_equipment,
    validate_location,
    validate_redry,
    validate_status_change,
)
from backend.lost_found_routes import register_lost_found_routes


class SqliteCursor:
    def __init__(self, conn):
        self.conn = conn
        self.lastrowid = None
        self._rows = []

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split()).replace("%s", "?")
        cur = self.conn.execute(text, tuple(params or ()))
        self.lastrowid = cur.lastrowid
        if cur.description:
            cols = [col[0] for col in cur.description]
            self._rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        return None


def _schema(conn):
    conn.executescript(
        """
        CREATE TABLE found_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          organization_id INT NOT NULL,
          client_request_id TEXT NOT NULL,
          reported_by_user_id INT NOT NULL,
          reporter_name TEXT NOT NULL,
          facility_name TEXT,
          shift_session_id INT,
          business_date TEXT NOT NULL,
          reported_at TEXT NOT NULL,
          location_kind TEXT NOT NULL,
          location_number TEXT,
          location_detail TEXT,
          location_label TEXT NOT NULL,
          notes TEXT,
          report_category TEXT NOT NULL DEFAULT 'orphan',
          redry_missing_ticket INT NOT NULL DEFAULT 0,
          redry_mesh_bag INT NOT NULL DEFAULT 0,
          redry_wrong_pocket INT NOT NULL DEFAULT 0,
          status TEXT NOT NULL,
          order_reference TEXT,
          status_comment TEXT,
          resolved_reason TEXT,
          revision INT NOT NULL,
          status_changed_at TEXT NOT NULL,
          status_changed_by_user_id INT,
          created_at TEXT,
          updated_at TEXT,
          UNIQUE (organization_id, client_request_id)
        );
        CREATE TABLE found_item_photos (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          organization_id INT NOT NULL,
          found_item_id INT,
          business_date TEXT,
          photo_role TEXT NOT NULL,
          blob_name TEXT NOT NULL,
          stored_filename TEXT NOT NULL,
          content_type TEXT NOT NULL,
          storage TEXT NOT NULL,
          captured_at TEXT NOT NULL,
          uploaded_by_user_id INT NOT NULL,
          created_at TEXT
        );
        CREATE TABLE found_item_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          organization_id INT NOT NULL,
          found_item_id INT,
          event_type TEXT NOT NULL,
          actor_user_id INT,
          actor_name TEXT,
          payload_json TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE found_item_accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          organization_id INT NOT NULL,
          business_date TEXT NOT NULL,
          found_item_id INT NOT NULL,
          revision INT NOT NULL,
          status_snapshot TEXT NOT NULL,
          escalated INT NOT NULL,
          comment TEXT,
          accounted_by_user_id INT NOT NULL,
          accounted_by_name TEXT,
          accounted_at TEXT NOT NULL,
          UNIQUE (organization_id, business_date, found_item_id)
        );
        CREATE TABLE found_item_reconciliations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          organization_id INT NOT NULL,
          business_date TEXT NOT NULL,
          status TEXT NOT NULL,
          started_at TEXT NOT NULL,
          completed_at TEXT,
          completed_by_user_id INT,
          activity_id INT,
          box_photo_id INT,
          UNIQUE (organization_id, business_date)
        );
        CREATE TABLE found_item_reconciliation_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          organization_id INT NOT NULL,
          business_date TEXT NOT NULL,
          activity_id INT,
          completed_by_user_id INT NOT NULL,
          completed_by_name TEXT,
          completed_at TEXT NOT NULL,
          box_photo_id INT,
          snapshot_json TEXT NOT NULL
        );
        """
    )


@pytest.fixture
def clock(monkeypatch):
    state = {"now": datetime(2026, 11, 7, 12, 0, 0)}

    def _now():
        return state["now"]

    monkeypatch.setattr("backend.lost_found.eastern_now_naive", _now)
    monkeypatch.setattr(
        "backend.lost_found.table_exists",
        lambda _cursor, name: str(name).startswith("found_"),
    )
    return state


@pytest.fixture
def db(clock):
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    return SqliteCursor(conn)


def _report(db, request_id="client-req-001", org=1, kind="washer", number="W23-30-VW", when=None, **kwargs):
    if when is not None:
        kwargs["_when"] = when
    return report_found_item(
        db,
        organization_id=org,
        client_request_id=request_id,
        user_id=kwargs.get("user_id", 8),
        reporter_name=kwargs.get("reporter_name", "Ana"),
        facility_name="VeeWash",
        shift_session_id=44,
        business_date=kwargs.get("business_date", date(2026, 11, 7)),
        location_kind=kind,
        location_number=number,
        location_detail=kwargs.get("detail"),
        notes=kwargs.get("notes"),
        report_category=kwargs.get("report_category", "orphan"),
        redry_flags=kwargs.get("redry_flags"),
    )


def test_redry_is_one_record_for_every_flag_combination():
    from itertools import combinations

    with pytest.raises(LostFoundError) as missing:
        validate_redry({}, "D1")
    assert missing.value.code == "redry_flag_required"
    without_dryer = validate_redry({"missing_ticket": True}, "")
    assert without_dryer["location_number"] is None
    mesh_only = validate_redry({"mesh_bag": True}, "")
    assert mesh_only["location_number"] is None
    with pytest.raises(LostFoundError) as pocket:
        validate_redry({"wrong_pocket": True}, "")
    assert pocket.value.code == "location_number_required"
    names = ("missing_ticket", "mesh_bag", "wrong_pocket")
    for picked in names:
        flags = {name: name == picked for name in names}
        cleaned = validate_redry(flags, "4" if picked == "wrong_pocket" else "")
        assert cleaned["location_kind"] == "dryer"
        assert cleaned[picked] is True
        assert sum(1 for name in names if cleaned[name]) == 1
        if picked == "wrong_pocket":
            assert cleaned["location_number"] == "4"
        else:
            assert cleaned["location_number"] is None
    for picked in combinations(names, 2):
        flags = {name: name in picked for name in names}
        with pytest.raises(LostFoundError) as several:
            validate_redry(flags, "4")
        assert several.value.code == "redry_one_reason"
    with pytest.raises(LostFoundError) as all_three:
        validate_redry({name: True for name in names}, "4")
    assert all_three.value.code == "redry_one_reason"
    with pytest.raises(LostFoundError) as stored:
        validate_status_change("stored", report_category="redry")
    assert stored.value.code == "invalid_status"
    resolved = validate_status_change("resolved", reason="Spoke with the dryer operator", report_category="redry")
    assert resolved["status"] == "resolved"


def test_historical_redry_row_keeps_every_stored_reason():
    from backend.lost_found import serialize_item

    item = serialize_item({
        "id": 9,
        "organization_id": 3,
        "reported_by_user_id": 23,
        "reporter_name": "Sarah Kamran",
        "reported_at": "2026-11-08 15:13:33",
        "business_date": "2026-11-08",
        "location_kind": "dryer",
        "location_number": "4",
        "location_detail": None,
        "location_label": "Dryer 4",
        "report_category": "redry",
        "redry_missing_ticket": 1,
        "redry_mesh_bag": 1,
        "redry_wrong_pocket": 1,
        "status": "new",
        "revision": 1,
        "status_changed_at": "2026-11-08 15:13:33",
    })
    assert item["redry_flags"] == {
        "missing_ticket": True,
        "mesh_bag": True,
        "wrong_pocket": True,
    }


def test_built_in_staff_roles_can_file_reports(monkeypatch):
    from backend.portal_system_users import user_is_reporting_service_account

    monkeypatch.setattr(
        "backend.portal_system_users.user_has_system_employment_category",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr("backend.portal_system_users.fetch_user_role_codes", lambda *_a, **_k: ["OPS"])
    assert user_is_reporting_service_account(object(), 4) is False
    monkeypatch.setattr("backend.portal_system_users.fetch_user_role_codes", lambda *_a, **_k: ["CLOCK"])
    assert user_is_reporting_service_account(object(), 33) is False
    monkeypatch.setattr("backend.portal_system_users.fetch_user_role_codes", lambda *_a, **_k: ["ADMIN"])
    assert user_is_reporting_service_account(object(), 15) is False
    monkeypatch.setattr("backend.portal_system_users.fetch_user_role_codes", lambda *_a, **_k: ["SYSTEM"])
    assert user_is_reporting_service_account(object(), 23) is True


def test_redry_stays_out_of_the_lost_and_found_box(db):
    item, created = _report(
        db,
        request_id="redry-all-three",
        report_category="redry",
        number="D4",
        redry_flags={"missing_ticket": True},
    )
    assert created is True
    assert item["report_category"] == "redry"
    assert item["redry_flags"] == {"missing_ticket": True, "mesh_bag": False, "wrong_pocket": False}
    view = reconciliation_view(db, organization_id=1, business_date=date(2026, 11, 7))
    assert view["items"] == []
    assert len(view["redry_items"]) == 1
    assert view["counts"] == {"orphan": 0, "redry": 1, "equipment": 0}
    assert view["equipment_items"] == []
    assert all(blocker["code"] != "box_photo_required" for blocker in view["blockers"])
    account_item(
        db,
        organization_id=1,
        business_date=date(2026, 11, 7),
        item_id=item["id"],
        actor_user_id=3,
        actor_name="Sam",
        action="confirm",
        comment="Reviewed the dryer photo",
    )
    closed = reconciliation_view(db, organization_id=1, business_date=date(2026, 11, 7))
    assert closed["blockers"] == []


def test_location_rules():
    assert validate_location("washer", "W23-30-VW")["location_label"] == "Washer W23-30-VW"
    assert validate_location("floor")["location_label"] == "Floor"
    assert validate_location("cart")["location_number"] is None
    assert validate_location("cart", "12")["location_label"] == "Cart 12"
    assert validate_location("other", detail="by the office")["location_label"] == "by the office"
    with pytest.raises(LostFoundError) as dryer:
        validate_location("dryer", "")
    assert dryer.value.code == "location_number_required"
    with pytest.raises(LostFoundError) as table:
        validate_location("folding_table", None)
    assert table.value.code == "location_number_required"
    with pytest.raises(LostFoundError) as other:
        validate_location("other", detail="x")
    assert other.value.code == "location_detail_required"


def test_veewash_numbers_and_equipment_are_separate_from_lost_and_found():
    from backend.lost_found_rules import et_calendar_date, format_et_desktop, matched_identifier
    from datetime import timezone

    catalog = veewash_issue_catalog()
    assert catalog["washers"] == [str(number) for number in range(1, 45)]
    assert catalog["dryers"] == [str(number) for number in range(1, 41)]
    assert catalog["folding_tables"] == [str(number) for number in range(1, 21)]
    assert catalog["washers"][0] == "1" and catalog["washers"][-1] == "44"
    assert catalog["dryers"][-1] == "40"
    assert catalog["folding_tables"][-1] == "20"
    assert matched_identifier("W44", catalog["washers"], code="identifier_not_configured") == "44"
    with pytest.raises(LostFoundError) as outside:
        matched_identifier("45", catalog["washers"], code="identifier_not_configured")
    assert outside.value.code == "identifier_not_configured"
    with pytest.raises(LostFoundError) as pocket:
        validate_redry({"wrong_pocket": True}, "9", allowed_pockets=["1", "2"])
    assert pocket.value.code == "pocket_not_designated"
    cleaned = validate_redry(
        {"wrong_pocket": True},
        "D1",
        bag_number="",
        allowed_pockets=["1"],
    )
    assert cleaned["location_number"] == "1"
    assert cleaned["redry_bag_number"] is None
    optional = validate_redry({"mesh_bag": True}, "", bag_number="MB-4")
    assert optional["location_number"] is None
    assert optional["redry_bag_number"] == "MB-4"
    washer = validate_equipment("washer", "12", allowed=catalog["washers"])
    assert washer["location_label"] == "Washer 12"
    assert "UTC" not in (format_et_desktop(datetime(2026, 11, 8, 20, 28)) or "")
    assert et_calendar_date(datetime(2026, 11, 8, 3, 30, tzinfo=timezone.utc)) == date(2026, 11, 7)
    assert et_calendar_date(datetime(2026, 3, 8, 4, 30, tzinfo=timezone.utc)) == date(2026, 3, 7)
    assert et_calendar_date(datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)) == date(2026, 3, 8)
    with pytest.raises(LostFoundError) as named:
        validate_equipment("other", "", detail="x")
    assert named.value.code == "equipment_name_required"
    other = validate_equipment("dehumidifier", "DH-1", allowed=[])
    assert other["location_kind"] == "dehumidifier"
    with pytest.raises(LostFoundError) as stored:
        validate_status_change("stored", report_category="equipment")
    assert stored.value.code == "invalid_status"
    repaired = validate_status_change(
        "resolved",
        reason="Back in service",
        report_category="equipment",
    )
    assert repaired["resolved_reason"] == "Back in service"


def test_equipment_report_does_not_block_reconciliation(db):
    item, created = _report(
        db,
        request_id="equipment-washer-down",
        report_category="equipment",
        kind="washer",
        number="W3",
        detail="will not start",
    )
    assert created is True
    assert item["report_category"] == "equipment"
    assert item["location_label"] == "Washer W3"
    view = reconciliation_view(db, organization_id=1, business_date=date(2026, 11, 7))
    assert view["items"] == []
    assert view["redry_items"] == []
    assert len(view["equipment_items"]) == 1
    assert view["blockers"] == []
    assert view["counts"]["equipment"] == 1


def test_issue_register_filters_use_eastern_days_and_employee(db):
    _report(db, request_id="day-a-ana", user_id=8, reporter_name="Ana", business_date=date(2026, 11, 7))
    _report(db, request_id="day-b-sam", user_id=9, reporter_name="Sam", business_date=date(2026, 11, 8), kind="dryer", number="4")
    _report(
        db,
        request_id="day-b-equip",
        user_id=8,
        reporter_name="Ana",
        business_date=date(2026, 11, 8),
        report_category="equipment",
        kind="washer",
        number="3",
    )
    today = search_issue_reports(db, 1, date_from=date(2026, 11, 8), date_to=date(2026, 11, 8))
    assert today["total"] == 2
    assert all(item["business_date"] == "2026-11-08" for item in today["items"])
    ana = search_issue_reports(
        db, 1, date_from=date(2026, 11, 7), date_to=date(2026, 11, 8), employee_id=8, category="equipment"
    )
    assert ana["total"] == 1
    assert ana["items"][0]["employee_name"] == "Ana"
    assert ana["items"][0]["report_category"] == "equipment"
    page = search_issue_reports(db, 1, date_from=date(2026, 11, 7), date_to=date(2026, 11, 8), page=1, page_size=2)
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert "UTC" not in (page["items"][0]["reported_at_display"] or "")


def test_shared_display_name_does_not_change_reporter_identity(db, monkeypatch):
    db.conn.executescript(
        """
        CREATE TABLE users (
          id INTEGER PRIMARY KEY,
          organization_id INT,
          display_name TEXT,
          username TEXT,
          active INT
        );
        CREATE TABLE payroll_profiles (
          user_id INT PRIMARY KEY,
          employee_id TEXT,
          first_name TEXT,
          last_name TEXT
        );
        CREATE TABLE roles (id INTEGER PRIMARY KEY, is_system INT);
        CREATE TABLE user_roles (user_id INT, role_id INT);
        INSERT INTO roles (id, is_system) VALUES (1, 1);
        INSERT INTO users (id, organization_id, display_name, username, active) VALUES
          (23, 1, 'Sarah', 'veetest', 1),
          (33, 1, 'Sarah Kamran', 'Sarah_kams', 1),
          (99, 1, 'Other Sarah', 'other', 1);
        INSERT INTO payroll_profiles (user_id, employee_id, first_name, last_name) VALUES
          (23, 'WP23', 'Sarah', 'Kamran'),
          (33, 'WP33', 'Sarah', 'Kamran');
        INSERT INTO user_roles (user_id, role_id) VALUES (23, 1);
        """
    )
    monkeypatch.setattr(
        "backend.lost_found.table_exists",
        lambda _cursor, name: str(name).startswith("found_")
        or name in {"users", "payroll_profiles", "roles", "user_roles"},
    )
    service, _created = _report(
        db,
        request_id="service-account-report",
        user_id=23,
        reporter_name="Sarah Kamran",
        business_date=date(2026, 11, 8),
    )
    employee, _created = _report(
        db,
        request_id="employee-account-report",
        user_id=33,
        reporter_name="Sarah Kamran",
        business_date=date(2026, 11, 8),
        kind="dryer",
        number="4",
    )
    stored = db.conn.execute(
        "SELECT id, reported_by_user_id, reporter_name FROM found_items ORDER BY id"
    ).fetchall()
    assert stored == [
        (service["id"], 23, "Sarah Kamran"),
        (employee["id"], 33, "Sarah Kamran"),
    ]
    by_service = search_issue_reports(
        db, 1, date_from=date(2026, 11, 8), date_to=date(2026, 11, 8), employee_id=23
    )
    by_employee = search_issue_reports(
        db, 1, date_from=date(2026, 11, 8), date_to=date(2026, 11, 8), employee_id=33
    )
    by_other = search_issue_reports(
        db, 1, date_from=date(2026, 11, 8), date_to=date(2026, 11, 8), employee_id=99
    )
    assert [item["id"] for item in by_service["items"]] == [service["id"]]
    assert [item["id"] for item in by_employee["items"]] == [employee["id"]]
    assert by_other["total"] == 0
    assert by_service["items"][0]["employee_code"] == "WP23"
    assert by_employee["items"][0]["employee_code"] == "WP33"
    assert by_service["items"][0]["employee_name"] != by_employee["items"][0]["employee_name"]
    assert by_service["items"][0]["reporter_name"] == "Sarah Kamran"
    directory = {person["id"]: person for person in list_issue_employees(db, 1)}
    assert set(directory) == {23, 33, 99}
    assert "WP23" in directory[23]["name"]
    assert "WP33" in directory[33]["name"]


def test_status_rules_do_not_touch_orders():
    returned = validate_status_change("returned", order_reference="R-100", comment="Given to guest")
    assert returned["order_reference"] == "R-100"
    with pytest.raises(LostFoundError) as missing_order:
        validate_status_change("returned", comment="left at desk")
    assert missing_order.value.code == "order_reference_required"
    with pytest.raises(LostFoundError) as missing_comment:
        validate_status_change("returned", order_reference="R-100", comment="")
    assert missing_comment.value.code == "comment_required"
    with pytest.raises(LostFoundError) as missing_reason:
        validate_status_change("resolved", reason="no")
    assert missing_reason.value.code == "reason_required"
    source = Path(__file__).resolve().parents[1].joinpath("lost_found.py").read_text(encoding="utf-8")
    assert "UPDATE orders" not in source
    assert "rinse_bag" not in source


def test_retry_keeps_one_record_and_original_photo(db, clock):
    item, created = _report(db)
    assert created is True
    add_item_photo(
        db,
        organization_id=1,
        found_item_id=item["id"],
        user_id=8,
        stored={
            "blob_name": "found-items/1/abc.jpg",
            "stored_filename": "abc.jpg",
            "content_type": "image/jpeg",
            "storage": "local",
        },
    )
    clock["now"] = datetime(2026, 11, 7, 13, 0, 0)
    again, created_again = _report(db)
    assert created_again is False
    assert again["id"] == item["id"]
    assert len(list_found_items(db, 1, business_date=date(2026, 11, 7))) == 1
    change_status(
        db,
        organization_id=1,
        item_id=item["id"],
        actor_user_id=3,
        actor_name="Supervisor",
        status="under_review",
        comment="Looking",
    )
    photos = db.conn.execute("SELECT captured_at, blob_name FROM found_item_photos").fetchall()
    assert photos == [("2026-11-07 12:00:00", "found-items/1/abc.jpg")]
    assert get_item(db, 2, item["id"]) is None


def test_reconciliation_requires_every_item_and_box_photo(db, clock):
    item, _created = _report(db, kind="floor", number=None)
    view = account_item(
        db,
        organization_id=1,
        business_date=date(2026, 11, 7),
        item_id=item["id"],
        actor_user_id=8,
        actor_name="Ana",
        action="update",
        status="stored",
    )
    assert any(b["code"] == "box_photo_required" for b in view["blockers"])
    with pytest.raises(LostFoundError):
        snapshot_reconciliation_on_complete(
            db,
            organization_id=1,
            user_id=8,
            user_name="Ana",
            business_date=date(2026, 11, 7),
            activity_id=50,
        )
    clock["now"] = datetime(2026, 11, 7, 12, 5, 0)
    add_box_photo(
        db,
        organization_id=1,
        business_date=date(2026, 11, 7),
        user_id=8,
        stored={
            "blob_name": "found-items/1/box.jpg",
            "stored_filename": "box.jpg",
            "content_type": "image/jpeg",
            "storage": "local",
        },
    )
    snapshot_reconciliation_on_complete(
        db,
        organization_id=1,
        user_id=8,
        user_name="Ana",
        business_date=date(2026, 11, 7),
        activity_id=50,
    )
    clock["now"] = datetime(2026, 11, 7, 12, 30, 0)
    late, created = _report(db, request_id="client-req-002", kind="cart", number="2")
    assert created is True
    with pytest.raises(LostFoundError) as stale:
        from backend.lost_found import assert_reconciliation_current_for_approval

        assert_reconciliation_current_for_approval(
            db, organization_id=1, business_date=date(2026, 11, 7)
        )
    assert stale.value.code == "snapshot_stale"
    account_item(
        db,
        organization_id=1,
        business_date=date(2026, 11, 7),
        item_id=late["id"],
        actor_user_id=8,
        actor_name="Ana",
        action="escalate",
        comment="Owner not here",
    )
    snapshot_reconciliation_on_complete(
        db,
        organization_id=1,
        user_id=8,
        user_name="Ana",
        business_date=date(2026, 11, 7),
        activity_id=50,
    )
    snaps = db.conn.execute("SELECT COUNT(*) FROM found_item_reconciliation_snapshots").fetchone()[0]
    assert snaps == 2


def test_carry_forward_does_not_duplicate(db, clock):
    clock["now"] = datetime(2026, 11, 6, 18, 0, 0)
    kept, _created = _report(db, request_id="old-open", business_date=date(2026, 11, 6), kind="dryer", number="D1")
    change_status(
        db,
        organization_id=1,
        item_id=kept["id"],
        actor_user_id=3,
        actor_name="Supervisor",
        status="stored",
    )
    done, _created = _report(db, request_id="old-done", business_date=date(2026, 11, 6), kind="floor", number=None)
    change_status(
        db,
        organization_id=1,
        item_id=done["id"],
        actor_user_id=3,
        actor_name="Supervisor",
        status="resolved",
        reason="Discarded with approval",
    )
    clock["now"] = datetime(2026, 11, 7, 9, 0, 0)
    today, _created = _report(db, request_id="today-back", kind="cart", number="")
    change_status(
        db,
        organization_id=1,
        item_id=today["id"],
        actor_user_id=3,
        actor_name="Supervisor",
        status="returned",
        order_reference="ORD-9",
        comment="Returned to customer",
    )
    from backend.lost_found import reconciliation_view

    view = reconciliation_view(db, 1, date(2026, 11, 7))
    labels = {item["location_label"]: item for item in view["items"]}
    assert "Dryer D1" in labels
    assert labels["Dryer D1"]["carried_forward"] is True
    assert "Cart" in labels
    assert "Floor" not in labels
    assert db.conn.execute("SELECT COUNT(*) FROM found_items WHERE id=?", (kept["id"],)).fetchone()[0] == 1


def test_scope_helpers_include_closed_items_from_the_same_day():
    day = "2026-11-07"
    items = [
        {"id": 1, "business_date": day, "status": "resolved"},
        {"id": 2, "business_date": "2026-11-06", "status": "stored"},
        {"id": 3, "business_date": "2026-11-06", "status": "returned"},
    ]
    chosen = select_reconciliation_items(items, day)
    assert [item["id"] for item in chosen] == [1, 2]
    blockers = reconciliation_blockers(chosen, {}, box_photo=None, started_at="2026-11-07 08:00:00")
    assert {b["code"] for b in blockers} == {"unaccounted", "box_photo_required"}
    stale = snapshot_is_current(
        {"items": [{"id": 1, "revision": 1}], "box_photo_id": None},
        [{"id": 1, "revision": 2, "status": "new"}, {"id": 9, "revision": 1, "status": "new"}],
        box_photo_id=None,
    )
    assert stale


def test_notify_only_the_reporting_organization(monkeypatch):
    seen = {}

    def dispatch(cursor, **kwargs):
        seen.update(kwargs)
        return {"ok": True}

    class Cursor:
        def execute(self, sql, params=None):
            self.params = params
            self._row = {"id": 1} if "SELECT" in sql.upper() else None

        def fetchone(self):
            return self._row

        def fetchall(self):
            return []

    monkeypatch.setattr(
        "backend.lost_found.table_exists",
        lambda _c, name: name in {"notification_event_definitions", "notification_event_audiences"},
    )
    monkeypatch.setattr("backend.notification_service.dispatch_notification_event", dispatch)
    notify_found_item(
        Cursor(),
        7,
        {
            "id": 4,
            "employee_name": "Ana",
            "location_label": "Washer W23-30-VW",
            "reported_at_display": "2026-11-07 12:00:00 ET (17:00:00 UTC)",
            "business_date": "2026-11-07",
        },
    )
    assert seen["organization_id"] == 7
    assert seen["channels"] == ["push"]
    assert seen["event_key"] == "lost_found.item_reported"
    assert "Washer W23-30-VW" in seen["body"]


def test_photo_storage_is_private_and_org_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("LOST_FOUND_MEDIA_ROOT", str(tmp_path))
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    stored = save_found_item_image(3, b"\xff\xd8\xff photo", "found.jpg")
    data, content_type = read_found_item_image(stored["blob_name"], 3)
    assert data.startswith(b"\xff\xd8")
    assert content_type == "image/jpeg"
    with pytest.raises(ValueError):
        read_found_item_image(stored["blob_name"], 4)
    with pytest.raises(ValueError):
        read_found_item_image("../secrets.jpg", 3)
    with pytest.raises(ValueError):
        save_found_item_image(3, b"%PDF", "note.pdf")


def test_desktop_route_uses_caller_org_and_rejects_other_roles(monkeypatch):
    app = Flask(__name__)
    state = {"org": None, "roles": ["OPS"]}

    def require_user(_cursor):
        return {"user_id": 9, "roles": state["roles"], "display_name": "Sam"}, None, None

    def user_org(_me):
        return 4

    register_lost_found_routes(
        app,
        require_user=require_user,
        user_org_id=user_org,
        fetch_user_roles=lambda *_a, **_k: [],
        get_request_ip=lambda: "127.0.0.1",
    )

    class Conn:
        def cursor(self, dictionary=True):
            return self

        def execute(self, *_a, **_k):
            return None

        def fetchone(self):
            return None

        def fetchall(self):
            return []

        def close(self):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr("backend.db.get_db", lambda: Conn())

    def fake_search(_cursor, organization_id, **_kwargs):
        state["org"] = organization_id
        return {"items": [], "total": 0, "page": 1, "page_size": 25}

    monkeypatch.setattr("backend.lost_found_routes.search_issue_reports", fake_search)
    monkeypatch.setattr("backend.lost_found_routes.list_issue_employees", lambda *_a, **_k: [])
    client = app.test_client()
    res = client.get("/api/lost-found?scope=today&date=2026-11-07")
    assert res.status_code == 200
    assert state["org"] == 4
    state["roles"] = ["RINSE"]
    denied = client.get("/api/lost-found")
    assert denied.status_code == 403


def test_photo_download_returns_the_original_bytes(monkeypatch):
    app = Flask(__name__)

    def require_user(_cursor):
        return {"user_id": 9, "roles": ["OPS"], "display_name": "Sam"}, None, None

    register_lost_found_routes(
        app,
        require_user=require_user,
        user_org_id=lambda _me: 3,
        fetch_user_roles=lambda *_a, **_k: [],
        get_request_ip=lambda: "127.0.0.1",
    )

    class Conn:
        def cursor(self, dictionary=True):
            return self

        def close(self):
            return None

    monkeypatch.setattr("backend.db.get_db", lambda: Conn())
    monkeypatch.setattr(
        "backend.lost_found_routes.get_photo_row",
        lambda _cursor, org_id, photo_id: {"id": photo_id, "blob_name": "org/photo.jpg", "organization_id": org_id},
    )
    original = b"\xff\xd8\xff original-report-photo"
    monkeypatch.setattr(
        "backend.lost_found_routes.read_found_item_image",
        lambda blob, org_id: (original, "image/jpeg"),
    )
    client = app.test_client()
    res = client.get("/api/lost-found/photos/15?download=1")
    assert res.status_code == 200
    assert res.data == original
    assert res.mimetype == "image/jpeg"
    assert "attachment" in res.headers.get("Content-Disposition", "")


def test_pin_report_requires_a_photo(monkeypatch):
    app = Flask(__name__)
    register_lost_found_routes(
        app,
        require_user=lambda _c: ({"roles": ["OPS"], "user_id": 1}, None, None),
        user_org_id=lambda _m: 1,
        fetch_user_roles=lambda *_a, **_k: [],
        get_request_ip=lambda: "127.0.0.1",
    )

    class Conn:
        def cursor(self, dictionary=True):
            return self

        def execute(self, *_a, **_k):
            return None

        def fetchone(self):
            return {"display_name": "VeeWash"}

        def close(self):
            return None

        def rollback(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr("backend.db.get_db", lambda: Conn())
    monkeypatch.setattr("backend.lost_found.table_exists", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "backend.lost_found_routes._gate_common",
        lambda *_a, **_k: (
            {"org_id": 1, "user_id": 8, "matched": {"display_name": "Ana"}, "session": {"id": 3}},
            None,
        ),
    )

    def _must_not_create(*_a, **_k):
        raise AssertionError("a missing photo must not create a report")

    monkeypatch.setattr("backend.portal_system_users.user_is_reporting_service_account", lambda *_a, **_k: False)
    monkeypatch.setattr("backend.lost_found_routes.report_found_item", _must_not_create)
    client = app.test_client()
    res = client.post(
        "/api/public/attendance/pin-lost-found/report",
        data={"organization_slug": "veewash", "hub_token": "hub", "client_request_id": "client-req-001", "location_kind": "floor"},
    )
    assert res.status_code == 400
    assert res.get_json()["code"] == "photo_required"


def test_report_submission_is_separate_from_supervisor_review(monkeypatch):
    app = Flask(__name__)
    seen = {}

    def gate(*_args, **kwargs):
        seen["require_shift"] = kwargs.get("require_shift")
        return (
            {"org_id": 1, "user_id": 8, "matched": {"display_name": "Ana"}, "session": None},
            None,
        )

    def require_user(_cursor):
        return {"user_id": 4, "roles": ["SUPERVISOR"], "display_name": "Pat"}, None, None

    register_lost_found_routes(
        app,
        require_user=require_user,
        user_org_id=lambda _me: 3,
        fetch_user_roles=lambda *_a, **_k: [],
        get_request_ip=lambda: "127.0.0.1",
    )

    class Conn:
        def cursor(self, dictionary=True):
            return self

        def execute(self, *_a, **_k):
            return None

        def fetchone(self):
            return None

        def fetchall(self):
            return []

        def close(self):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr("backend.db.get_db", lambda: Conn())
    flags = {"system": False}
    monkeypatch.setattr("backend.lost_found_routes._gate_common", gate)
    monkeypatch.setattr(
        "backend.portal_system_users.user_is_reporting_service_account",
        lambda *_a, **_k: flags["system"],
    )
    monkeypatch.setattr(
        "backend.lost_found_routes.reconciliation_view",
        lambda *_a, **_k: {"items": [], "ready": True},
    )
    monkeypatch.setattr("backend.lost_found_routes.find_client_item", lambda *_a, **_k: {"id": 9})

    def _record(*_a, **kwargs):
        seen["reports"] = seen.get("reports", []) + [kwargs]
        return {"id": 9}, False

    monkeypatch.setattr("backend.lost_found_routes.report_found_item", _record)
    client = app.test_client()
    pin = client.post(
        "/api/public/attendance/pin-lost-found/report",
        data={
            "organization_slug": "veewash",
            "hub_token": "hub",
            "client_request_id": "client-req-001",
            "location_kind": "floor",
            "report_category": "orphan",
        },
    )
    assert pin.status_code == 200
    assert seen["require_shift"] is False
    assert seen["reports"][0]["user_id"] == 8
    signed_in = client.post(
        "/api/lost-found/report",
        data={
            "client_request_id": "client-req-002",
            "location_kind": "floor",
            "report_category": "orphan",
        },
    )
    assert signed_in.status_code == 200
    assert seen["reports"][1]["user_id"] == 4
    reconciliation = client.post(
        "/api/public/attendance/pin-lost-found/reconciliation",
        json={"organization_slug": "veewash", "hub_token": "hub"},
    )
    assert reconciliation.status_code == 200
    assert seen["require_shift"] is True
    flags["system"] = True
    blocked = client.post(
        "/api/public/attendance/pin-lost-found/report",
        data={
            "organization_slug": "veewash",
            "hub_token": "hub",
            "client_request_id": "client-req-003",
            "location_kind": "floor",
            "report_category": "orphan",
        },
    )
    assert blocked.status_code == 403
    assert len(seen["reports"]) == 2
    review = client.post("/api/lost-found/9/status", json={"status": "under_review", "comment": "Checked"})
    assert review.status_code == 403


def test_staff_photo_submission_is_saved_and_listed(monkeypatch, tmp_path):
    """A non-supervisor can file a real photograph, and that report is a register row."""
    import io

    from backend.issues_register import compose_register

    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"
    monkeypatch.setenv("LOST_FOUND_MEDIA_ROOT", str(tmp_path))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    app = Flask(__name__)
    saved = {}

    def require_user(_cursor):
        return {"user_id": 28, "roles": ["FOLDER"], "display_name": "Ana Folder"}, None, None

    register_lost_found_routes(
        app,
        require_user=require_user,
        user_org_id=lambda _me: 3,
        fetch_user_roles=lambda *_a, **_k: ["FOLDER"],
        get_request_ip=lambda: "127.0.0.1",
    )

    class Conn:
        def cursor(self, dictionary=True):
            return self

        def execute(self, *_a, **_k):
            return None

        def fetchone(self):
            return None

        def fetchall(self):
            return []

        def close(self):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr("backend.db.get_db", lambda: Conn())
    monkeypatch.setattr("backend.portal_system_users.user_is_reporting_service_account", lambda *_a, **_k: False)

    def _record(*_a, **kwargs):
        saved["report"] = kwargs
        return {"id": 41}, True

    def _photo(*_a, **kwargs):
        saved["photo"] = kwargs

    monkeypatch.setattr("backend.lost_found_routes.find_client_item", lambda *_a, **_k: None)
    monkeypatch.setattr("backend.lost_found_routes.reporter_name_for_user", lambda *_a, **_k: "Ana Folder")
    monkeypatch.setattr("backend.lost_found_routes.report_found_item", _record)
    monkeypatch.setattr("backend.lost_found_routes.add_item_photo", _photo)
    monkeypatch.setattr("backend.lost_found_routes.get_item", lambda *_a, **_k: {"id": 41})
    monkeypatch.setattr("backend.lost_found_routes.notify_found_item", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "backend.lost_found._hydrate",
        lambda *_a, **_k: [{
            "id": 41,
            "report_category": "equipment",
            "status": "new",
            "employee_name": "Ana Folder",
            "location_label": "Washer 4",
            "reported_at_display": "2026-11-13 17:00:00 ET",
            "photos": [{"id": 7}],
        }],
    )
    client = app.test_client()
    res = client.post(
        "/api/lost-found/report",
        data={
            "client_request_id": "photo-req-001",
            "report_category": "equipment",
            "location_kind": "washer",
            "location_number": "4",
            "employee_id": "99",
            "organization_id": "9",
            "reporter_name": "Someone Else",
            "photos": (io.BytesIO(jpeg), "washer.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["ok"] is True
    assert body["created"] is True
    assert body["item"]["photos"][0]["id"] == 7
    assert saved["report"]["user_id"] == 28
    assert saved["report"]["organization_id"] == 3
    assert saved["report"]["reporter_name"] == "Ana Folder"
    assert saved["report"]["report_category"] == "equipment"
    assert client.get("/api/lost-found/photos/7").status_code == 403
    assert client.post("/api/lost-found/41/status", json={"status": "resolved", "reason": "fixed"}).status_code == 403
    stored = list(tmp_path.rglob("*.jpg"))
    assert len(stored) == 1
    assert stored[0].read_bytes().startswith(b"\xff\xd8")
    register = compose_register([], [{
        "id": 41,
        "report_category": "equipment",
        "status": "new",
        "employee_name": "Ana Folder",
        "location_label": "Washer 4",
        "reported_at": "2026-11-13 17:00:00",
        "photos": [{"id": 7}],
    }])
    assert register["rows"][0]["category_label"] == "Equipment Not Working"
    assert register["rows"][0]["photo_count"] == 1
    assert register["summary"]["by_source"]["employee"] == 1


def test_activity_code_is_end_of_day_task():
    assert ACTIVITY_CODE == "custom_lost_found_reconciliation"
