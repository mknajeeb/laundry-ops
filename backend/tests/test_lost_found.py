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
    notify_found_item,
    reconciliation_view,
    report_found_item,
    snapshot_reconciliation_on_complete,
)
from backend.lost_found_photos import read_found_item_image, save_found_item_image
from backend.lost_found_rules import (
    ACTIVITY_CODE,
    LostFoundError,
    reconciliation_blockers,
    select_reconciliation_items,
    snapshot_is_current,
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
    with pytest.raises(LostFoundError) as pocket:
        validate_redry({"missing_ticket": True}, "")
    assert pocket.value.code == "location_number_required"
    names = ("missing_ticket", "mesh_bag", "wrong_pocket")
    for size in (1, 2, 3):
        for picked in combinations(names, size):
            flags = {name: name in picked for name in names}
            cleaned = validate_redry(flags, "D4")
            assert cleaned["location_kind"] == "dryer"
            assert cleaned["location_number"] == "D4"
            assert [name for name in names if cleaned[name]] == list(picked)
    with pytest.raises(LostFoundError) as stored:
        validate_status_change("stored", report_category="redry")
    assert stored.value.code == "invalid_status"
    resolved = validate_status_change("resolved", reason="Spoke with the dryer operator", report_category="redry")
    assert resolved["status"] == "resolved"


def test_redry_stays_out_of_the_lost_and_found_box(db):
    item, created = _report(
        db,
        request_id="redry-all-three",
        report_category="redry",
        number="D4",
        redry_flags={"missing_ticket": True, "mesh_bag": True, "wrong_pocket": True},
    )
    assert created is True
    assert item["report_category"] == "redry"
    assert item["redry_flags"] == {"missing_ticket": True, "mesh_bag": True, "wrong_pocket": True}
    view = reconciliation_view(db, organization_id=1, business_date=date(2026, 11, 7))
    assert view["items"] == []
    assert len(view["redry_items"]) == 1
    assert view["counts"] == {"orphan": 0, "redry": 1}
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

    def fake_list(_cursor, organization_id, **_kwargs):
        state["org"] = organization_id
        return []

    monkeypatch.setattr("backend.lost_found_routes.list_found_items", fake_list)
    client = app.test_client()
    res = client.get("/api/lost-found?scope=today&date=2026-11-07")
    assert res.status_code == 200
    assert state["org"] == 4
    state["roles"] = ["RINSE"]
    denied = client.get("/api/lost-found")
    assert denied.status_code == 403


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

    monkeypatch.setattr("backend.lost_found_routes.report_found_item", _must_not_create)
    client = app.test_client()
    res = client.post(
        "/api/public/attendance/pin-lost-found/report",
        data={"organization_slug": "veewash", "hub_token": "hub", "client_request_id": "client-req-001", "location_kind": "floor"},
    )
    assert res.status_code == 400
    assert res.get_json()["code"] == "photo_required"


def test_activity_code_is_end_of_day_task():
    assert ACTIVITY_CODE == "custom_lost_found_reconciliation"
