"""Phase 5B.1 / 5B.2 — Employee Mobile PIN Access."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.employee_mobile_pin_access import (
    AUDIT_ACTION,
    DENIED_MODULE_MESSAGE,
    INIT_MODE_LEGACY_GRANT,
    INIT_MODE_NEW_ORG,
    MobilePinAccessBackfillError,
    MobilePinAccessDeniedError,
    assert_employee_allows_module,
    employee_allows_module,
    enable_switch_role_for_org_active_users,
    ensure_new_employee_mobile_pin_access,
    ensure_org_mobile_pin_access_backfill,
    initialize_new_org_mobile_pin_access_marker,
    resolve_employee_mobile_pin_access,
    run_org_mobile_pin_access_legacy_backfill,
    save_employee_mobile_pin_access,
    serialize_mobile_pin_access,
)


class FakeCursor:
    def __init__(self):
        self.access = {}  # (org, user) -> dict of five bools
        self.users = {(3, 10), (3, 11), (3, 12), (3, 42), (99, 50)}
        self.inactive_users = set()  # (org_id, user_id)
        self.backfill_orgs = {}  # org -> employees_granted
        self.backfill_modes = {}  # org -> init_mode
        self.pin_users = []  # (org, user)
        self.org_ids = [3]
        self.all_org_users = []  # optional richer skip list: (org, uid, active, has_pin)
        self._result = None
        self._results = []
        self.rowcount = 0
        self._has_init_mode = True
        self.fail_insert_user_ids = set()

    def execute(self, sql, params=None):
        sql_n = " ".join(str(sql).split())
        params = params or ()

        if "CREATE TABLE IF NOT EXISTS employee_mobile_pin_access" in sql_n:
            return
        if "ALTER TABLE employee_mobile_pin_access_backfill" in sql_n:
            self._has_init_mode = True
            return
        if "INFORMATION_SCHEMA.COLUMNS" in sql_n:
            # table_has_column(cursor, table, col)
            col = params[1] if len(params) > 1 else ""
            self._result = {"ok": 1} if col == "init_mode" and self._has_init_mode else None
            return
        if "INFORMATION_SCHEMA.TABLES" in sql_n:
            name = params[0] if params else ""
            self._result = {"ok": 1} if name else None
            return
        if "SELECT GET_LOCK" in sql_n:
            self._result = {"got": 1}
            return
        if "SELECT RELEASE_LOCK" in sql_n:
            self._result = {"released": 1}
            return
        if "FROM employee_mobile_pin_access_backfill WHERE organization_id" in sql_n:
            oid = int(params[0])
            self._result = {"ok": 1} if oid in self.backfill_orgs else None
            return
        if "INSERT INTO employee_mobile_pin_access_backfill" in sql_n or (
            "INSERT IGNORE INTO employee_mobile_pin_access_backfill" in sql_n
        ):
            oid = int(params[0])
            # new_org hook: VALUES (%s, NOW(), 0, %s) → (oid, mode)
            # legacy mark: VALUES (%s, NOW(), %s, %s) → (oid, granted, mode)
            if len(params) == 2:
                granted = 0
                mode = str(params[1])
            else:
                granted = int(params[1])
                mode = str(params[2]) if len(params) > 2 else INIT_MODE_LEGACY_GRANT
            if "INSERT IGNORE" in sql_n and oid in self.backfill_orgs:
                self.rowcount = 0
                return
            if oid not in self.backfill_orgs:
                self.backfill_orgs[oid] = granted
                self.backfill_modes[oid] = mode
                self.rowcount = 1
            else:
                self.rowcount = 0
            return
        if "SELECT id FROM organizations WHERE id" in sql_n:
            oid = int(params[0])
            self._result = {"id": oid} if oid in self.org_ids else None
            return
        if (
            "SELECT u.id AS user_id" in sql_n
            and "FROM users u" in sql_n
            and "attendance_pin_hash IS NOT NULL" in sql_n
        ):
            oid = int(params[0])
            self._results = [
                {"user_id": uid} for porg, uid in self.pin_users if porg == oid
            ]
            return
        if (
            "SELECT user_id FROM employee_mobile_pin_access" in sql_n
            and "user_id IN" in sql_n
        ):
            oid = int(params[0])
            uids = [int(p) for p in params[1:]]
            self._results = [
                {"user_id": uid}
                for uid in uids
                if (oid, uid) in self.access
            ]
            return
        if (
            "INSERT INTO employee_mobile_pin_access" in sql_n
            and "VALUES" in sql_n
            and "ON DUPLICATE KEY" not in sql_n
            and "INSERT IGNORE" not in sql_n
            and "allow_clock, allow_switch_role" in sql_n
        ):
            # Single-row insert with explicit module flags (org, uid, 5 flags, …)
            if (
                len(params) >= 7
                and int(params[2]) in (0, 1)
                and int(params[3]) in (0, 1)
            ):
                org, uid = int(params[0]), int(params[1])
                self.access[(org, uid)] = {
                    "clock": bool(params[2]),
                    "switch_role": bool(params[3]),
                    "checklist": bool(params[4]),
                    "inventory": bool(params[5]),
                    "revenue_cost": bool(params[6]),
                }
                self.rowcount = 1
                return
            # Multi-row all-true insert: (org, uid) pairs in params
            for i in range(0, len(params), 2):
                org, uid = int(params[i]), int(params[i + 1])
                if uid in self.fail_insert_user_ids:
                    raise MobilePinAccessBackfillError("simulated insert failure")
                if (org, uid) in self.access:
                    raise Exception("duplicate key")
                self.access[(org, uid)] = {
                    "clock": True,
                    "switch_role": True,
                    "checklist": True,
                    "inventory": True,
                    "revenue_cost": True,
                }
            self.rowcount = len(params) // 2
            return
        if (
            "FROM users u" in sql_n
            and "LEFT JOIN payroll_profiles" in sql_n
            and "has_pin" in sql_n
        ):
            oid = int(params[0])
            if self.all_org_users:
                self._results = [
                    {
                        "user_id": uid,
                        "active": 1 if active else 0,
                        "has_pin": 1 if has_pin else 0,
                    }
                    for porg, uid, active, has_pin in self.all_org_users
                    if porg == oid
                ]
            else:
                # Derive from users + pin_users
                pin_set = {uid for porg, uid in self.pin_users if porg == oid}
                rows = []
                for porg, uid in self.users:
                    if porg != oid:
                        continue
                    rows.append(
                        {
                            "user_id": uid,
                            "active": 0 if (porg, uid) in self.inactive_users else 1,
                            "has_pin": 1 if uid in pin_set else 0,
                        }
                    )
                self._results = rows
            return
        if (
            "FROM employee_mobile_pin_access" in sql_n
            and "SELECT organization_id, user_id" in sql_n
            and "LIMIT 1" in sql_n
        ):
            org, uid = int(params[0]), int(params[1])
            a = self.access.get((org, uid))
            if a:
                self._result = {
                    "organization_id": org,
                    "user_id": uid,
                    "allow_clock": 1 if a["clock"] else 0,
                    "allow_switch_role": 1 if a["switch_role"] else 0,
                    "allow_checklist": 1 if a["checklist"] else 0,
                    "allow_inventory": 1 if a["inventory"] else 0,
                    "allow_revenue_cost": 1 if a["revenue_cost"] else 0,
                    "updated_at": None,
                    "updated_by_user_id": None,
                    "created_at": None,
                }
            else:
                self._result = None
            return
        if "SELECT id FROM users WHERE id" in sql_n and "organization_id" in sql_n:
            uid, oid = int(params[0]), int(params[1])
            if (oid, uid) in self.inactive_users:
                self._result = None
            elif (oid, uid) in self.users:
                self._result = {"id": uid}
            else:
                self._result = None
            return
        if (
            "INSERT IGNORE INTO employee_mobile_pin_access" in sql_n
            and "VALUES" in sql_n
            and "SELECT" not in sql_n
        ):
            org, uid = int(params[0]), int(params[1])
            if (org, uid) not in self.access:
                if len(params) >= 7:
                    self.access[(org, uid)] = {
                        "clock": bool(params[2]),
                        "switch_role": bool(params[3]),
                        "checklist": bool(params[4]),
                        "inventory": bool(params[5]),
                        "revenue_cost": bool(params[6]),
                    }
                else:
                    self.access[(org, uid)] = {
                        "clock": False,
                        "switch_role": True,
                        "checklist": False,
                        "inventory": False,
                        "revenue_cost": False,
                    }
            return
        if (
            "UPDATE employee_mobile_pin_access" in sql_n
            and "allow_switch_role = 1" in sql_n
        ):
            oid, uid = int(params[1]), int(params[2])
            a = self.access.get((oid, uid))
            if a is not None:
                a["switch_role"] = True
            self.rowcount = 1 if a is not None else 0
            return
        if (
            "SELECT id AS user_id FROM users" in sql_n
            and "active = 1" in sql_n
            and "organization_id" in sql_n
        ):
            oid = int(params[0])
            self._results = [
                {"user_id": uid}
                for porg, uid in self.users
                if porg == oid and (porg, uid) not in self.inactive_users
            ]
            return
        if (
            "SELECT id AS user_id FROM users" in sql_n
            and "active = 0 OR active IS NULL" in sql_n
        ):
            oid = int(params[0])
            self._results = [
                {"user_id": uid}
                for porg, uid in self.inactive_users
                if porg == oid
            ]
            return
        if "INSERT INTO employee_mobile_pin_access" in sql_n and "ON DUPLICATE KEY" in sql_n:
            org, uid = int(params[0]), int(params[1])
            self.access[(org, uid)] = {
                "clock": bool(params[2]),
                "switch_role": bool(params[3]),
                "checklist": bool(params[4]),
                "inventory": bool(params[5]),
                "revenue_cost": bool(params[6]),
            }
            return
        self._result = None

    def fetchone(self):
        r = self._result
        self._result = None
        return r

    def fetchall(self):
        r = self._results
        self._results = []
        return r

    def close(self):
        return None


class FakeConn:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor
        self.autocommit = True
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, dictionary=True):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _legacy_backfill(cur: FakeCursor, org_id: int = 3, *, dry_run: bool = False):
    return run_org_mobile_pin_access_legacy_backfill(
        FakeConn(cur), org_id, dry_run=dry_run
    )


def test_ensure_org_does_not_auto_grant():
    cur = FakeCursor()
    cur.pin_users = [(3, 10), (3, 11)]
    ensure_org_mobile_pin_access_backfill(cur, 3)
    assert cur.access == {}
    assert cur.backfill_orgs == {}


def test_migration_pin_employee_gets_all_true():
    cur = FakeCursor()
    cur.pin_users = [(3, 10), (3, 11)]
    report = _legacy_backfill(cur, 3)
    assert report["ok"] is True
    assert report["marker"] == "written"
    assert report["rows_inserted"] == 2
    assert resolve_employee_mobile_pin_access(cur, 3, 10) == {
        "clock": True,
        "switch_role": True,
        "checklist": True,
        "inventory": True,
        "revenue_cost": True,
    }
    # Idempotent
    report2 = _legacy_backfill(cur, 3)
    assert report2["already_complete"] is True
    assert report2["rows_inserted"] == 0
    assert cur.access[(3, 10)]["clock"] is True
    assert cur.backfill_modes[3] == INIT_MODE_LEGACY_GRANT


def test_legacy_backfill_dry_run_writes_nothing():
    cur = FakeCursor()
    cur.pin_users = [(3, 10), (3, 11)]
    report = _legacy_backfill(cur, 3, dry_run=True)
    assert report["ok"] is True
    assert report["dry_run"] is True
    assert report["marker"] == "would_write"
    assert report["planned_inserts"] == [10, 11]
    assert cur.access == {}
    assert cur.backfill_orgs == {}


def test_legacy_backfill_single_org_isolation():
    cur = FakeCursor()
    cur.org_ids = [3, 99]
    cur.pin_users = [(3, 10), (99, 50)]
    cur.users.add((99, 50))
    report = _legacy_backfill(cur, 3)
    assert report["ok"] is True
    assert (3, 10) in cur.access
    assert (99, 50) not in cur.access
    assert 99 not in cur.backfill_orgs


def test_legacy_backfill_rolls_back_without_marker_on_failure():
    cur = FakeCursor()
    cur.pin_users = [(3, 10), (3, 11)]
    cur.fail_insert_user_ids = {11}
    conn = FakeConn(cur)
    with pytest.raises(MobilePinAccessBackfillError):
        run_org_mobile_pin_access_legacy_backfill(conn, 3, dry_run=False)
    assert conn.rollbacks >= 1
    assert 3 not in cur.backfill_orgs


def test_new_org_marker_then_new_employee_role_default_on():
    cur = FakeCursor()
    assert initialize_new_org_mobile_pin_access_marker(cur, 3) is True
    assert cur.backfill_modes[3] == INIT_MODE_NEW_ORG
    assert cur.backfill_orgs[3] == 0
    assert initialize_new_org_mobile_pin_access_marker(cur, 3) is False
    ensure_new_employee_mobile_pin_access(cur, 3, 12, actor_user_id=1)
    assert resolve_employee_mobile_pin_access(cur, 3, 12) == {
        "clock": False,
        "switch_role": True,
        "checklist": False,
        "inventory": False,
        "revenue_cost": False,
    }


def test_new_employee_after_backfill_gets_role_default_on():
    cur = FakeCursor()
    cur.pin_users = [(3, 10)]
    _legacy_backfill(cur, 3)
    ensure_new_employee_mobile_pin_access(cur, 3, 12, actor_user_id=1)
    assert resolve_employee_mobile_pin_access(cur, 3, 12) == {
        "clock": False,
        "switch_role": True,
        "checklist": False,
        "inventory": False,
        "revenue_cost": False,
    }


def test_enable_switch_role_for_org_active_users_preserves_other_modules():
    cur = FakeCursor()
    cur.users = {(3, 10), (3, 11), (3, 12)}
    cur.inactive_users = {(3, 99)}
    cur.users.add((3, 99))
    cur.backfill_orgs[3] = 0
    cur.backfill_modes[3] = INIT_MODE_LEGACY_GRANT
    cur.access[(3, 10)] = {
        "clock": False,
        "switch_role": False,
        "checklist": True,
        "inventory": False,
        "revenue_cost": True,
    }
    cur.access[(3, 11)] = {
        "clock": False,
        "switch_role": True,
        "checklist": False,
        "inventory": True,
        "revenue_cost": False,
    }
    # user 12 has no row yet
    conn = FakeConn(cur)
    report = enable_switch_role_for_org_active_users(conn, 3, dry_run=False, actor_user_id=1)
    assert report["active_users"] == 3
    assert report["role_on_before"] == 1
    assert report["role_on_after"] == 3
    assert report["rows_updated"] == 1
    assert report["rows_inserted"] == 1
    assert report["excluded_inactive"] == 1
    assert resolve_employee_mobile_pin_access(cur, 3, 10) == {
        "clock": False,
        "switch_role": True,
        "checklist": True,
        "inventory": False,
        "revenue_cost": True,
    }
    assert resolve_employee_mobile_pin_access(cur, 3, 11)["inventory"] is True
    assert resolve_employee_mobile_pin_access(cur, 3, 12) == {
        "clock": False,
        "switch_role": True,
        "checklist": False,
        "inventory": False,
        "revenue_cost": False,
    }


def test_missing_row_after_backfill_denies_access():
    cur = FakeCursor()
    cur.pin_users = [(3, 10)]
    _legacy_backfill(cur, 3)
    # User 12 never got a row
    assert resolve_employee_mobile_pin_access(cur, 3, 12)["clock"] is False
    assert employee_allows_module(cur, 3, 12, "inventory") is False
    assert employee_allows_module(cur, 3, 12, "revenue_cost") is False
    with pytest.raises(MobilePinAccessDeniedError):
        assert_employee_allows_module(cur, 3, 12, "checklist")


def test_temporary_unmarked_org_missing_row_allows_all():
    """Bounded deploy-window fallback: unmarked org + missing row → allow all."""
    cur = FakeCursor()
    with patch(
        "backend.employee_mobile_pin_access.ensure_org_mobile_pin_access_backfill",
        side_effect=lambda cursor, oid: None,
    ), patch(
        "backend.employee_mobile_pin_access._org_is_backfilled", return_value=False
    ), patch(
        "backend.employee_mobile_pin_access.get_access_row", return_value=None
    ), patch(
        "backend.employee_mobile_pin_access.ensure_employee_mobile_pin_access_tables"
    ):
        assert resolve_employee_mobile_pin_access(cur, 3, 99)["clock"] is True


def test_save_and_audit_only_changed():
    cur = FakeCursor()
    cur.pin_users = [(3, 10)]
    _legacy_backfill(cur, 3)
    events = []

    def audit(*args, **kwargs):
        events.append((args, kwargs))

    save_employee_mobile_pin_access(
        cur,
        3,
        10,
        grants={
            "clock": True,
            "switch_role": False,
            "checklist": True,
            "inventory": True,
            "revenue_cost": False,
        },
        actor_user_id=5,
        write_audit_fn=audit,
    )
    assert len(events) == 1
    assert events[0][0][3] == AUDIT_ACTION
    modules = events[0][1]["new"]["modules"]
    assert set(modules.keys()) == {"switch_role", "revenue_cost"}
    assert modules["switch_role"] is False

    # No-op save → no audit
    events.clear()
    save_employee_mobile_pin_access(
        cur,
        3,
        10,
        grants={
            "clock": True,
            "switch_role": False,
            "checklist": True,
            "inventory": True,
            "revenue_cost": False,
        },
        actor_user_id=5,
        write_audit_fn=audit,
    )
    assert events == []


def test_assert_denies_module():
    from backend.employee_mobile_pin_access import (
        ENFORCED_EMPLOYEE_MOBILE_PIN_MODULES,
        assert_optional_pin_hub_module,
    )

    assert ENFORCED_EMPLOYEE_MOBILE_PIN_MODULES == frozenset(
        {"switch_role", "checklist", "inventory", "revenue_cost"}
    )
    cur = FakeCursor()
    cur.backfill_orgs[3] = 0
    cur.access[(3, 10)] = {
        "clock": False,
        "switch_role": False,
        "checklist": False,
        "inventory": False,
        "revenue_cost": False,
    }
    with pytest.raises(MobilePinAccessDeniedError):
        assert_employee_allows_module(cur, 3, 10, "switch_role")
    with pytest.raises(MobilePinAccessDeniedError):
        assert_employee_allows_module(cur, 3, 10, "checklist")
    with pytest.raises(MobilePinAccessDeniedError):
        assert_employee_allows_module(cur, 3, 10, "inventory")
    with pytest.raises(MobilePinAccessDeniedError):
        assert_employee_allows_module(cur, 3, 10, "revenue_cost")
    # Clock remains stored but not enforced.
    assert_employee_allows_module(cur, 3, 10, "clock")
    # Optional unlock helper: omitted module is a no-op; enforced modules deny.
    assert_optional_pin_hub_module(cur, 3, 10, None)
    assert_optional_pin_hub_module(cur, 3, 10, "")
    with pytest.raises(MobilePinAccessDeniedError):
        assert_optional_pin_hub_module(cur, 3, 10, "inventory")
    with pytest.raises(MobilePinAccessDeniedError):
        assert_optional_pin_hub_module(cur, 3, 10, "revenue_cost")


def test_resolve_hub_features_enforces_role_checklist_inventory_and_revenue_cost():
    """Employee OFF hides Role, Checklist, Inventory, and Revenue & Cost."""
    from backend.employee_pin_hub import resolve_hub_features

    matched = {"id": 10, "_roles": []}
    emp = {
        "clock": True,
        "switch_role": False,
        "checklist": False,
        "inventory": False,
        "revenue_cost": False,
    }
    with patch(
        "backend.employee_pin_hub.load_pin_menu_settings",
        return_value={
            "enabled": True,
            "allow_clock_from_hub": True,
            "features": {
                "switch_role": True,
                "checklist": True,
                "inventory": True,
                "revenue_cost": True,
                },
        },
    ), patch(
        "backend.employee_pin_hub.is_category_role_tracking_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._tenant_module_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._permission_keys", return_value=set()
    ):
        feats = resolve_hub_features(
            MagicMock(),
            org_id=3,
            matched=matched,
            employee_module_access=emp,
        )
    assert feats["switch_role"]["allowed"] is False
    assert feats["switch_role"]["employee_allowed"] is False
    assert feats["checklist"]["allowed"] is False
    assert feats["checklist"]["employee_allowed"] is False
    assert feats["inventory"]["allowed"] is False
    assert feats["inventory"]["employee_allowed"] is False
    assert feats["revenue_cost"]["allowed"] is False
    assert feats["revenue_cost"]["employee_allowed"] is False


def test_resolve_hub_features_role_allowed_when_employee_grants():
    from backend.employee_pin_hub import resolve_hub_features

    matched = {"id": 10, "_roles": []}
    emp = {
        "clock": False,
        "switch_role": True,
        "checklist": False,
        "inventory": False,
        "revenue_cost": False,
    }
    with patch(
        "backend.employee_pin_hub.load_pin_menu_settings",
        return_value={
            "enabled": True,
            "allow_clock_from_hub": True,
            "features": {
                "switch_role": True,
                "checklist": True,
                "inventory": True,
                "revenue_cost": True,
                },
        },
    ), patch(
        "backend.employee_pin_hub.is_category_role_tracking_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._tenant_module_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._permission_keys", return_value=set()
    ):
        feats = resolve_hub_features(
            MagicMock(),
            org_id=3,
            matched=matched,
            employee_module_access=emp,
        )
    assert feats["switch_role"]["allowed"] is True
    assert feats["switch_role"]["employee_allowed"] is True
    assert feats["inventory"]["allowed"] is False
    assert feats["inventory"]["employee_allowed"] is False


def test_resolve_hub_features_inventory_off_hides_tile():
    from backend.employee_pin_hub import resolve_hub_features

    matched = {"id": 10, "_roles": []}
    emp = {
        "clock": False,
        "switch_role": False,
        "checklist": False,
        "inventory": False,
        "revenue_cost": False,
    }
    with patch(
        "backend.employee_pin_hub.load_pin_menu_settings",
        return_value={
            "enabled": True,
            "allow_clock_from_hub": True,
            "features": {
                "switch_role": True,
                "checklist": True,
                "inventory": True,
                "revenue_cost": True,
                },
        },
    ), patch(
        "backend.employee_pin_hub.is_category_role_tracking_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._tenant_module_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._permission_keys", return_value=set()
    ):
        feats = resolve_hub_features(
            MagicMock(),
            org_id=3,
            matched=matched,
            employee_module_access=emp,
        )
    assert feats["inventory"]["allowed"] is False
    assert feats["inventory"]["employee_allowed"] is False
    assert feats["inventory"]["org_enabled"] is True
    assert feats["switch_role"]["allowed"] is False


def test_org_feature_off_overrides_employee_allow():
    from backend.employee_pin_hub import resolve_hub_features

    matched = {"id": 10, "_roles": []}
    emp = {k: True for k in ("clock", "switch_role", "checklist", "inventory", "revenue_cost")}
    with patch(
        "backend.employee_pin_hub.load_pin_menu_settings",
        return_value={
            "enabled": True,
            "allow_clock_from_hub": True,
            "features": {
                "switch_role": False,
                "checklist": True,
                "inventory": True,
                "revenue_cost": True,
                },
        },
    ), patch(
        "backend.employee_pin_hub.is_category_role_tracking_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._tenant_module_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._permission_keys", return_value=set()
    ):
        feats = resolve_hub_features(
            MagicMock(), org_id=3, matched=matched, employee_module_access=emp
        )
    assert feats["switch_role"]["org_enabled"] is False
    assert feats["switch_role"]["allowed"] is False


def test_attendance_snapshot_employee_allow_clock():
    from backend.employee_pin_hub import attendance_snapshot_for_hub

    with patch(
        "backend.employee_pin_hub.shared_device_attendance_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub.load_pin_menu_settings",
        return_value={"enabled": True, "allow_clock_from_hub": False, "features": {}},
    ), patch(
        "backend.employee_pin_hub._active_shift", return_value=None
    ):
        snap = attendance_snapshot_for_hub(
            MagicMock(),
            3,
            10,
            employee_module_access={
                "clock": False,
                "switch_role": True,
                "checklist": True,
                "inventory": True,
                "revenue_cost": True,
                },
        )
    assert snap["allow_clock_from_hub"] is False
    assert snap["employee_allow_clock"] is False


def test_role_switch_open_denied_without_employee_access():
    from backend.attendance_pin_role_switch import perform_pin_role_switch

    conn = MagicMock()
    access_cur = FakeCursor()
    access_cur.backfill_orgs[3] = 1
    access_cur.access[(3, 10)] = {
        "clock": True,
        "switch_role": False,
        "checklist": False,
        "inventory": False,
        "revenue_cost": False,
    }
    conn.cursor.return_value = access_cur

    with patch(
        "backend.attendance_pin_role_switch.payroll_profiles_active", return_value=True
    ), patch(
        "backend.attendance_pin_role_switch.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash"},
    ), patch(
        "backend.attendance_pin_role_switch.shared_device_attendance_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.is_rate_limited", return_value=False
    ), patch(
        "backend.attendance_pin_role_switch.resolve_user_by_attendance_pin",
        return_value={"id": 10, "display_name": "Test"},
    ), patch(
        "backend.attendance_pin_role_switch._active_shift",
        return_value={"id": 99},
    ), patch(
        "backend.attendance_pin_role_switch.is_category_role_tracking_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.record_pin_attempt"
    ):
        body, status = perform_pin_role_switch(
            conn, "veewash", "1234", lambda *_: [], "1.1.1.1"
        )
    assert status == 403
    assert DENIED_MODULE_MESSAGE in body["error"]


def test_role_change_mutation_denied_without_employee_access():
    from backend.attendance_pin_role_switch import perform_pin_role_switch

    conn = MagicMock()
    access_cur = FakeCursor()
    access_cur.backfill_orgs[3] = 1
    access_cur.access[(3, 10)] = {
        "clock": True,
        "switch_role": False,
        "checklist": True,
        "inventory": True,
        "revenue_cost": True,
    }
    conn.cursor.return_value = access_cur

    with patch(
        "backend.attendance_pin_role_switch.payroll_profiles_active", return_value=True
    ), patch(
        "backend.attendance_pin_role_switch.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash"},
    ), patch(
        "backend.attendance_pin_role_switch.shared_device_attendance_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.is_rate_limited", return_value=False
    ), patch(
        "backend.attendance_pin_role_switch.resolve_user_by_attendance_pin",
        return_value={"id": 10, "display_name": "Test"},
    ), patch(
        "backend.attendance_pin_role_switch._active_shift",
        return_value={"id": 99},
    ), patch(
        "backend.attendance_pin_role_switch.is_category_role_tracking_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.record_pin_attempt"
    ), patch(
        "backend.attendance_pin_role_switch.start_category_role_segment"
    ) as start_seg:
        body, status = perform_pin_role_switch(
            conn,
            "veewash",
            "1234",
            lambda *_: [],
            "1.1.1.1",
            category_id=1,
            role_id=2,
            idempotency_key="abc",
        )
    assert status == 403
    assert DENIED_MODULE_MESSAGE in body["error"]
    start_seg.assert_not_called()


def test_role_mutation_revoked_mid_session_blocks_next_call():
    """Open succeeds while allowed; after revoke, mutation re-reads DB and denies."""
    from backend.attendance_pin_role_switch import perform_pin_role_switch

    conn = MagicMock()
    access_cur = FakeCursor()
    access_cur.backfill_orgs[3] = 1
    access_cur.access[(3, 10)] = {
        "clock": True,
        "switch_role": True,
        "checklist": True,
        "inventory": True,
        "revenue_cost": True,
    }
    conn.cursor.return_value = access_cur

    with patch(
        "backend.attendance_pin_role_switch.payroll_profiles_active", return_value=True
    ), patch(
        "backend.attendance_pin_role_switch.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash"},
    ), patch(
        "backend.attendance_pin_role_switch.shared_device_attendance_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.is_rate_limited", return_value=False
    ), patch(
        "backend.attendance_pin_role_switch.resolve_user_by_attendance_pin",
        return_value={"id": 10, "display_name": "Test"},
    ), patch(
        "backend.attendance_pin_role_switch._active_shift",
        return_value={"id": 99},
    ), patch(
        "backend.attendance_pin_role_switch.is_category_role_tracking_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.record_pin_attempt"
    ), patch(
        "backend.attendance_pin_role_switch.get_open_job_segment", return_value=None
    ), patch(
        "backend.attendance_pin_role_switch.list_active_selection_tree",
        return_value={"categories": []},
    ):
        open_body, open_status = perform_pin_role_switch(
            conn, "veewash", "1234", lambda *_: [], "1.1.1.1"
        )
    assert open_status == 200
    assert open_body.get("needs_selection") is True

    # Revoke while "page" is open
    access_cur.access[(3, 10)]["switch_role"] = False

    with patch(
        "backend.attendance_pin_role_switch.payroll_profiles_active", return_value=True
    ), patch(
        "backend.attendance_pin_role_switch.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash"},
    ), patch(
        "backend.attendance_pin_role_switch.shared_device_attendance_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.is_rate_limited", return_value=False
    ), patch(
        "backend.attendance_pin_role_switch.resolve_user_by_attendance_pin",
        return_value={"id": 10, "display_name": "Test"},
    ), patch(
        "backend.attendance_pin_role_switch._active_shift",
        return_value={"id": 99},
    ), patch(
        "backend.attendance_pin_role_switch.is_category_role_tracking_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.record_pin_attempt"
    ), patch(
        "backend.attendance_pin_role_switch.start_category_role_segment"
    ) as start_seg:
        mut_body, mut_status = perform_pin_role_switch(
            conn,
            "veewash",
            "1234",
            lambda *_: [],
            "1.1.1.1",
            category_id=1,
            role_id=2,
            idempotency_key="revoked-1",
        )
    assert mut_status == 403
    assert DENIED_MODULE_MESSAGE in mut_body["error"]
    start_seg.assert_not_called()


def test_role_allowed_returns_unfiltered_selection_tree():
    """Stage A only gates the module; selection tree behavior is unchanged."""
    from backend.attendance_pin_role_switch import perform_pin_role_switch

    conn = MagicMock()
    access_cur = FakeCursor()
    access_cur.backfill_orgs[3] = 1
    access_cur.access[(3, 10)] = {
        "clock": True,
        "switch_role": True,
        "checklist": True,
        "inventory": True,
        "revenue_cost": True,
    }
    conn.cursor.return_value = access_cur
    tree = {
        "categories": [
            {"id": 1, "name": "Rinse WF", "roles": [{"role_id": 10, "role_name": "Operator"}]}
        ]
    }

    with patch(
        "backend.attendance_pin_role_switch.payroll_profiles_active", return_value=True
    ), patch(
        "backend.attendance_pin_role_switch.fetch_organization_by_slug",
        return_value={"id": 3, "slug": "veewash"},
    ), patch(
        "backend.attendance_pin_role_switch.shared_device_attendance_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.is_rate_limited", return_value=False
    ), patch(
        "backend.attendance_pin_role_switch.resolve_user_by_attendance_pin",
        return_value={"id": 10, "display_name": "Test"},
    ), patch(
        "backend.attendance_pin_role_switch._active_shift",
        return_value={"id": 99},
    ), patch(
        "backend.attendance_pin_role_switch.is_category_role_tracking_enabled",
        return_value=True,
    ), patch(
        "backend.attendance_pin_role_switch.record_pin_attempt"
    ), patch(
        "backend.attendance_pin_role_switch.get_open_job_segment", return_value=None
    ), patch(
        "backend.attendance_pin_role_switch.list_active_selection_tree",
        return_value=tree,
    ) as list_tree:
        body, status = perform_pin_role_switch(
            conn, "veewash", "1234", lambda *_: [], "1.1.1.1"
        )
    assert status == 200
    assert body["selection_tree"] == tree
    list_tree.assert_called_once()
    assert list_tree.call_args.args[1] == 3
