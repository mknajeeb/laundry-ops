"""Unified Step-1 Edit Bag: validation, apply, conflict, and undo semantics."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.rinse_step1_edit_bag import (
    apply_unified_bag_edit,
    undo_bag_edit,
    validate_edit_draft,
)

D1 = date(2026, 7, 22)
ORG = 3
BAG = "BAGWF1"


# ---------------------------------------------------------------------------
# validate_edit_draft (pure function, no cursor)
# ---------------------------------------------------------------------------


def test_no_chargeable_conflicts_with_positive_quantities():
    errors = validate_edit_draft(
        {
            "no_chargeable": True,
            "bulk_items": [{"workitem_id": 1, "quantity": 2}],
        },
        service_type="WF",
    )
    assert "no_chargeable_conflicts_with_items" in errors


def test_no_chargeable_alone_is_valid():
    errors = validate_edit_draft(
        {"no_chargeable": True, "bulk_items": []},
        service_type="WF",
    )
    assert errors == []


def test_hd_service_rejects_positive_bulk_quantity():
    errors = validate_edit_draft(
        {"bulk_items": [{"workitem_id": 1, "quantity": 1}]},
        service_type="HD",
    )
    assert "bulk_workitems_wf_only" in errors


def test_hd_service_allows_zero_quantity_bulk_lines():
    errors = validate_edit_draft(
        {"bulk_items": [{"workitem_id": 1, "quantity": 0}]},
        service_type="HD",
    )
    assert errors == []


def test_bulk_quantity_must_be_non_negative_integer():
    errors = validate_edit_draft(
        {"bulk_items": [{"workitem_id": 1, "quantity": -1}]},
        service_type="WF",
    )
    assert "bulk_quantity_must_be_non_negative" in errors

    errors2 = validate_edit_draft(
        {"bulk_items": [{"workitem_id": 1, "quantity": 1.5}]},
        service_type="WF",
    )
    assert "bulk_quantity_must_be_integer" in errors2


def test_zero_weight_is_valid_blank_normalizes_to_null():
    errors = validate_edit_draft({"pre_weight_lbs": 0, "post_weight_lbs": ""}, service_type="WF")
    assert errors == []


def test_negative_weight_is_invalid():
    errors = validate_edit_draft({"post_weight_lbs": -5}, service_type="WF")
    assert "post_weight_lbs_must_be_non_negative" in errors


# ---------------------------------------------------------------------------
# FakeCursor — supports the SQL surface exercised by apply_unified_bag_edit /
# undo_bag_edit, including a real (unmocked) save_bag_bulk_workitems() call.
# ---------------------------------------------------------------------------


def _day_bag_row(**overrides):
    base = {
        "id": 1,
        "organization_id": ORG,
        "shift_date_et": D1,
        "bag_id": BAG,
        "service_type": "WF",
        "rush_status": "RUSH",
        "new_or_carryover": "new_today",
        "workload_entry_type": "facility_dirty_scan",
        "workload_entry_timestamp": datetime(2026, 7, 22, 6, 0, 0),
        "pre_weight_lbs": 10.0,
        "post_weight_lbs": None,
        "weight_lbs": 10.0,
        "canonical_completion_status": None,
        "canonical_completion_timestamp": None,
        "canonical_completion_employee": None,
        "effective_status": "pending",
        "review_reason_codes_json": None,
        "portal_status_at_sync": "at_vendor",
        "last_present_scrape": None,
        "first_confirmed_absent_scrape": None,
        "disposition": None,
        "bag_snapshot_json": None,
        "created_at": datetime(2026, 7, 22, 6, 0, 0),
        "updated_at": datetime(2026, 7, 22, 6, 0, 0),
        "manager_edit_version": 0,
        "productivity_employee_name": None,
        "productivity_completed_at": None,
        "productivity_weight_lbs": None,
        "productivity_credit_eligible": None,
        "productivity_exclusion_reason": None,
    }
    base.update(overrides)
    return base


class _FakeCursor:
    """Fake cursor covering bulk workitems + shift-monitor day bags + bag edits."""

    def __init__(self, day_bags: dict | None = None):
        self.tables = {
            "rinse_bulk_workitems": [],
            "rinse_bag_bulk_workitems": [],
            "rinse_bag_bulk_workitem_resolutions": [],
            "rinse_bag_bulk_workitem_audits": [],
            "rinse_step1_bag_edits": [],
            "rinse_step1_bag_edit_deltas": [],
        }
        self.day_bags: dict[tuple, dict] = day_bags or {}
        self._id = 1
        self._edit_id = 1
        self._delta_id = 1
        self._tick = 0
        self.lastrowid = 0
        self.rowcount = 0
        self._result = []
        self.connection = SimpleNamespace(commit=lambda: None)

    # -- helpers ----------------------------------------------------------
    def _bump_updated_at(self, row: dict) -> None:
        self._tick += 1
        row["updated_at"] = datetime(2026, 7, 22, 6, 0, 0) + timedelta(seconds=self._tick)

    def _bump_manager_edit_version(self, row: dict) -> None:
        row["manager_edit_version"] = int(row.get("manager_edit_version") or 0) + 1
        self._bump_updated_at(row)

    # -- main dispatcher ----------------------------------------------------
    def execute(self, sql, params=None):
        params = params or ()
        s = " ".join(str(sql).split()).lower()
        self.rowcount = 0

        if "information_schema" in s or "show tables" in s:
            self._result = [{"c": 1}]
            return
        if s.startswith("create table") or s.startswith("alter table"):
            self._result = []
            return

        # -- rinse_shift_monitor_day_bags -----------------------------------
        if "rinse_shift_monitor_day_bags" in s:
            if s.startswith("select *"):
                org, day = int(params[0]), params[1]
                bag_ids = list(params[2:])
                rows = [
                    dict(v)
                    for k, v in self.day_bags.items()
                    if k[0] == org and k[1] == day and k[2] in bag_ids
                ]
                self._result = rows
                return
            if s.startswith("select bag_snapshot_json"):
                org, day, bag = int(params[0]), params[1], params[2]
                row = self.day_bags.get((org, day, bag))
                self._result = [{"bag_snapshot_json": row.get("bag_snapshot_json")}] if row else []
                return
            if s.startswith("update") and "manager_edit_version = manager_edit_version + 1" in s:
                org, day, bag, expected = params
                row = self.day_bags.get((int(org), day, bag))
                if row is not None and int(row.get("manager_edit_version") or 0) == int(expected):
                    self._bump_manager_edit_version(row)
                    self.rowcount = 1
                else:
                    self.rowcount = 0
                self._result = []
                return
            if s.startswith("update") and "set pre_weight_lbs" in s:
                pre, post, weight, org, day, bag = params
                row = self.day_bags.get((int(org), day, bag))
                if row is not None:
                    row["pre_weight_lbs"] = pre
                    row["post_weight_lbs"] = post
                    row["weight_lbs"] = weight
                    self._bump_updated_at(row)
                    self.rowcount = 1
                self._result = []
                return
            if s.startswith("update") and "set service_type" in s:
                svc, rush, snap_json, org, day, bag = params
                row = self.day_bags.get((int(org), day, bag))
                if row is not None:
                    row["service_type"] = svc
                    row["rush_status"] = rush
                    row["bag_snapshot_json"] = snap_json
                    self._bump_updated_at(row)
                    self.rowcount = 1
                self._result = []
                return
            if s.startswith("update") and "set productivity_employee_name" in s:
                emp, comp_at, lbs, eligible, excl, org, day, bag = params
                row = self.day_bags.get((int(org), day, bag))
                if row is not None:
                    row["productivity_employee_name"] = emp
                    row["productivity_completed_at"] = comp_at
                    row["productivity_weight_lbs"] = lbs
                    row["productivity_credit_eligible"] = eligible
                    row["productivity_exclusion_reason"] = excl
                    self.rowcount = 1
                self._result = []
                return
            if s.startswith("update") and "set updated_at = current_timestamp" in s:
                org, day, bag = params[:3]
                row = self.day_bags.get((int(org), day, bag))
                if row is not None:
                    self._bump_updated_at(row)
                    self.rowcount = 1
                self._result = []
                return
            self._result = []
            return
        # -- rinse_step1_bag_edits / deltas -----------------------------------
        if s.startswith("insert into rinse_step1_bag_edits"):
            (
                org, day, bag, reason, actor_uid, actor_name, before_json, after_json,
                outcome, expected_dt, parent_id,
            ) = params
            row = {
                "id": self._edit_id,
                "organization_id": int(org),
                "shift_date_et": day,
                "bag_id": bag,
                "reason": reason,
                "actor_user_id": actor_uid,
                "actor_display_name": actor_name,
                "before_json": before_json,
                "after_json": after_json,
                "outcome_action": outcome,
                "expected_updated_at": expected_dt,
                "parent_edit_id": parent_id,
                "is_undo": 0,
                "created_at": datetime(2026, 7, 22, 6, 0, 0) + timedelta(seconds=self._edit_id),
            }
            self.tables["rinse_step1_bag_edits"].append(row)
            self.lastrowid = self._edit_id
            self._edit_id += 1
            self._result = []
            return
        if s.startswith("update rinse_step1_bag_edits"):
            parent_id, org, new_id = params
            for r in self.tables["rinse_step1_bag_edits"]:
                if r["organization_id"] == int(org) and r["id"] == int(new_id):
                    r["is_undo"] = 1
                    r["parent_edit_id"] = int(parent_id)
            self._result = []
            return
        if "from rinse_step1_bag_edits" in s and "order by id desc" in s:
            org, day, bag = int(params[0]), params[1], params[2]
            rows = [
                r
                for r in self.tables["rinse_step1_bag_edits"]
                if r["organization_id"] == org and r["shift_date_et"] == day and r["bag_id"] == bag
            ]
            rows.sort(key=lambda r: r["id"], reverse=True)
            self._result = rows[:1]
            return
        if "from rinse_step1_bag_edits" in s and "and id = %s" in s:
            org, edit_id = int(params[0]), int(params[1])
            self._result = [
                r
                for r in self.tables["rinse_step1_bag_edits"]
                if r["organization_id"] == org and r["id"] == edit_id
            ][:1]
            return
        if s.startswith("insert into rinse_step1_bag_edit_deltas"):
            edit_id, field_name, before_val, after_val = params
            self.tables["rinse_step1_bag_edit_deltas"].append(
                {
                    "id": self._delta_id,
                    "edit_id": edit_id,
                    "field_name": field_name,
                    "before_value": before_val,
                    "after_value": after_val,
                }
            )
            self._delta_id += 1
            self._result = []
            return

        # -- rinse_bulk_workitems maintenance (adapted from test_bulk_workitems) --
        if "from rinse_bulk_workitems" in s and "count(*)" in s:
            org = int(params[0])
            c = sum(1 for r in self.tables["rinse_bulk_workitems"] if r["organization_id"] == org)
            self._result = [{"c": c}]
            return
        if s.startswith("insert into rinse_bulk_workitems"):
            row = {
                "id": self._id,
                "organization_id": int(params[0]),
                "name": params[1],
                "current_unit_price": params[2],
                "active": int(params[3]),
                "display_order": int(params[4]),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "created_by_user_id": params[5],
                "created_by_display_name": params[6],
                "updated_by_user_id": params[7],
                "updated_by_display_name": params[8],
            }
            self.tables["rinse_bulk_workitems"].append(row)
            self.lastrowid = self._id
            self._id += 1
            self._result = []
            return
        if "from rinse_bulk_workitems" in s and "where organization_id" in s and "and id" in s:
            org, wid = int(params[0]), int(params[1])
            self._result = [
                r
                for r in self.tables["rinse_bulk_workitems"]
                if r["organization_id"] == org and r["id"] == wid
            ][:1]
            return
        if "from rinse_bulk_workitems" in s and "where organization_id" in s:
            org = int(params[0])
            rows = [r for r in self.tables["rinse_bulk_workitems"] if r["organization_id"] == org]
            if "active = 1" in s:
                rows = [r for r in rows if int(r["active"]) == 1]
            self._result = sorted(rows, key=lambda r: (r["display_order"], r["name"]))
            return
        if "from rinse_cleaner_ticket_presence" in s:
            self._result = []
            return
        if s.startswith("insert into rinse_bag_bulk_workitems"):
            row = {
                "id": self._id,
                "organization_id": int(params[0]),
                "shift_date_et": params[1],
                "bag_id": params[2],
                "workitem_id": int(params[3]),
                "workitem_name_snapshot": params[4],
                "unit_price_snapshot": params[5],
                "quantity": int(params[6]),
                "line_total": params[7],
            }
            self.tables["rinse_bag_bulk_workitems"].append(row)
            self.lastrowid = self._id
            self._id += 1
            self._result = []
            return
        if s.startswith("delete from rinse_bag_bulk_workitems"):
            org, day, bag = int(params[0]), params[1], params[2]
            self.tables["rinse_bag_bulk_workitems"] = [
                r
                for r in self.tables["rinse_bag_bulk_workitems"]
                if not (r["organization_id"] == org and r["shift_date_et"] == day and r["bag_id"] == bag)
            ]
            self._result = []
            return
        if s.startswith("delete from rinse_bag_bulk_workitem_resolutions"):
            org, day, bag = int(params[0]), params[1], params[2]
            self.tables["rinse_bag_bulk_workitem_resolutions"] = [
                r
                for r in self.tables["rinse_bag_bulk_workitem_resolutions"]
                if not (r["organization_id"] == org and r["shift_date_et"] == day and r["bag_id"] == bag)
            ]
            self._result = []
            return
        if "from rinse_bag_bulk_workitems" in s and "shift_date_et" in s:
            org = int(params[0])
            day = params[1]
            bags = set(params[2:]) if len(params) > 2 else None
            rows = [
                r
                for r in self.tables["rinse_bag_bulk_workitems"]
                if r["organization_id"] == org and r["shift_date_et"] == day
            ]
            if bags is not None:
                rows = [r for r in rows if r["bag_id"] in bags]
            if "quantity > 0" in s:
                rows = [r for r in rows if int(r.get("quantity") or 0) > 0]
            self._result = rows
            return
        if s.startswith("insert into rinse_bag_bulk_workitem_resolutions"):
            org, day, bag = int(params[0]), params[1], params[2]
            self.tables["rinse_bag_bulk_workitem_resolutions"] = [
                r
                for r in self.tables["rinse_bag_bulk_workitem_resolutions"]
                if not (r["organization_id"] == org and r["shift_date_et"] == day and r["bag_id"] == bag)
            ]
            self.tables["rinse_bag_bulk_workitem_resolutions"].append(
                {
                    "organization_id": org,
                    "shift_date_et": day,
                    "bag_id": bag,
                    "resolution_type": params[3],
                    "no_charge_reason": params[4],
                    "items_total": params[5],
                }
            )
            self._result = []
            return
        if "from rinse_bag_bulk_workitem_resolutions" in s:
            org, day = int(params[0]), params[1]
            bags = set(params[2:]) if len(params) > 2 else None
            rows = [
                r
                for r in self.tables["rinse_bag_bulk_workitem_resolutions"]
                if r["organization_id"] == org and r["shift_date_et"] == day
            ]
            if bags is not None:
                rows = [r for r in rows if r["bag_id"] in bags]
            self._result = rows
            return
        if s.startswith("insert into rinse_bag_bulk_workitem_audits"):
            self.tables["rinse_bag_bulk_workitem_audits"].append({"params": params})
            self._result = []
            return
        if "from rinse_bag_bulk_workitem_audits" in s:
            self._result = []
            return

        self._result = []

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


@pytest.fixture
def cur():
    row = _day_bag_row()
    return _FakeCursor(day_bags={(ORG, D1, BAG): row})


@pytest.fixture(autouse=True)
def _patch_table_exists(monkeypatch):
    import backend.rinse_bulk_workitems as bulk_mod
    import backend.rinse_step1_edit_bag as edit_mod
    import backend.ta_helpers as ta_helpers_mod
    import backend.rinse_veewash_shift_day as shift_day_mod

    monkeypatch.setattr(bulk_mod, "table_exists", lambda c, t: True)
    monkeypatch.setattr(edit_mod, "table_exists", lambda c, t: False)
    # write_operator_audit_log lazily imports table_exists from ta_helpers; keep it
    # returning False so it no-ops instead of touching a real audit_log table.
    monkeypatch.setattr(ta_helpers_mod, "table_exists", lambda c, t: False)
    monkeypatch.setattr(shift_day_mod, "get_day_record", lambda *a, **k: None)
    yield


# ---------------------------------------------------------------------------
# apply_unified_bag_edit — conflict detection
# ---------------------------------------------------------------------------


def test_conflict_409_when_expected_updated_at_is_stale():
    stale_before = {
        "bag_id": BAG,
        "service_type": "WF",
        "rush_flag": "RUSH",
        "entry_at": None,
        "entry_source": None,
        "rack": None,
        "pre_weight_lbs": 10.0,
        "post_weight_lbs": None,
        "bulk_items": [],
        "no_chargeable": False,
        "no_charge_reason": None,
        "dashboard_status": "pending",
        "outcome": "pending",
        "completion_at": None,
        "completed_by": None,
        "updated_at": "2026-07-22T06:05:00",
    }
    cursor = _FakeCursor()
    with patch(
        "backend.rinse_step1_edit_bag.capture_bag_edit_state",
        return_value=stale_before,
    ):
        out = apply_unified_bag_edit(
            cursor,
            ORG,
            bag_id=BAG,
            selected_date_et=D1,
            reason="weight fix",
            draft={"post_weight_lbs": 12},
            expected_updated_at="2026-07-22T06:00:00",  # stale vs. current 06:05
        )
    assert out["ok"] is False
    assert out["error"] == "conflict"
    assert out["status"] == 409
    assert out["latest"] == stale_before
    # No edit row should have been written on conflict.
    assert cursor.tables["rinse_step1_bag_edits"] == []


def test_no_conflict_when_expected_updated_at_matches(cur):
    out = apply_unified_bag_edit(
        cur,
        ORG,
        bag_id=BAG,
        selected_date_et=D1,
        reason="weight fix",
        draft={"post_weight_lbs": 12},
        expected_updated_at="2026-07-22T06:00:00",
    )
    assert out["ok"] is True


# ---------------------------------------------------------------------------
# apply_unified_bag_edit — bulk workitems + weight in one atomic apply
# ---------------------------------------------------------------------------


def test_bath_mat_and_weight_applied_together(cur):
    from backend.rinse_bulk_workitems import create_workitem

    bath = create_workitem(cur, ORG, name="Bath Mat", current_unit_price=4, display_order=10)

    out = apply_unified_bag_edit(
        cur,
        ORG,
        bag_id=BAG,
        selected_date_et=D1,
        reason="Manager found bath mat + updated weight",
        draft={
            "bulk_items": [{"workitem_id": bath["id"], "quantity": 2}],
            "post_weight_lbs": 22.5,
        },
        actor_user_id=7,
        actor_display_name="Manager Mo",
    )

    assert out["ok"] is True
    assert out["edit_id"] == 1
    assert out["undo_token"] == out["edit_id"]
    after = out["after"]
    assert after["post_weight_lbs"] == 22.5
    assert after["bulk_items"] == [
        {
            "workitem_id": bath["id"],
            "name": "Bath Mat",
            "quantity": 2,
            "unit_price": 4.0,
            "line_total": 8.0,
        }
    ]
    field_names = {d["field_name"] for d in out["deltas"]}
    assert "post_weight_lbs" in field_names
    assert "bulk_items" in field_names

    # Persisted directly on the day bag row too.
    row = cur.day_bags[(ORG, D1, BAG)]
    assert row["post_weight_lbs"] == 22.5
    assert row["weight_lbs"] == 22.5

    # Exactly one parent edit row for this single atomic apply.
    assert len(cur.tables["rinse_step1_bag_edits"]) == 1


def test_validation_failure_blocks_write_before_any_mutation(cur):
    out = apply_unified_bag_edit(
        cur,
        ORG,
        bag_id=BAG,
        selected_date_et=D1,
        reason="bad draft",
        draft={"no_chargeable": True, "bulk_items": [{"workitem_id": 1, "quantity": 3}]},
    )
    assert out["ok"] is False
    assert out["error"] == "validation_failed"
    assert "no_chargeable_conflicts_with_items" in out["errors"]
    assert cur.tables["rinse_step1_bag_edits"] == []


# ---------------------------------------------------------------------------
# no partial write — an exception from a sub-step must not leave a parent row
# ---------------------------------------------------------------------------


def test_no_partial_write_when_bulk_save_raises(cur):
    with patch(
        "backend.rinse_bulk_workitems.save_bag_bulk_workitems",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            apply_unified_bag_edit(
                cur,
                ORG,
                bag_id=BAG,
                selected_date_et=D1,
                reason="try bulk edit",
                draft={"bulk_items": [{"workitem_id": 1, "quantity": 1}]},
            )
    assert cur.tables["rinse_step1_bag_edits"] == []
    assert cur.tables["rinse_step1_bag_edit_deltas"] == []


# ---------------------------------------------------------------------------
# undo_bag_edit
# ---------------------------------------------------------------------------


def test_undo_restores_prior_state_when_latest(cur):
    first = apply_unified_bag_edit(
        cur,
        ORG,
        bag_id=BAG,
        selected_date_et=D1,
        reason="bump weight",
        draft={"post_weight_lbs": 30.0},
    )
    assert first["ok"] is True
    assert cur.day_bags[(ORG, D1, BAG)]["post_weight_lbs"] == 30.0

    out = undo_bag_edit(
        cur,
        ORG,
        edit_id=first["edit_id"],
        actor_user_id=9,
        actor_display_name="Manager Mo",
    )

    assert out["ok"] is True
    assert out["is_undo"] is True
    assert out["restored_from_edit_id"] == first["edit_id"]
    # Weight restored back to the original (None) pre-edit value.
    assert cur.day_bags[(ORG, D1, BAG)]["post_weight_lbs"] is None

    # The new undo edit row is flagged is_undo=1 and links back to the original.
    new_row = next(r for r in cur.tables["rinse_step1_bag_edits"] if r["id"] == out["edit_id"])
    assert new_row["is_undo"] == 1
    assert new_row["parent_edit_id"] == first["edit_id"]


def test_undo_blocked_when_newer_edit_exists(cur):
    first = apply_unified_bag_edit(
        cur,
        ORG,
        bag_id=BAG,
        selected_date_et=D1,
        reason="bump weight",
        draft={"post_weight_lbs": 30.0},
    )
    second = apply_unified_bag_edit(
        cur,
        ORG,
        bag_id=BAG,
        selected_date_et=D1,
        reason="bump weight again",
        draft={"post_weight_lbs": 40.0},
    )
    assert first["ok"] is True and second["ok"] is True

    out = undo_bag_edit(cur, ORG, edit_id=first["edit_id"])
    assert out["ok"] is False
    assert out["error"] == "newer_edit_exists"
    # State is untouched by the blocked undo attempt.
    assert cur.day_bags[(ORG, D1, BAG)]["post_weight_lbs"] == 40.0


def test_undo_missing_edit_returns_error(cur):
    out = undo_bag_edit(cur, ORG, edit_id=999)
    assert out["ok"] is False
    assert out["error"] == "edit_not_found"


# ---------------------------------------------------------------------------
# Production reproducer: 42EN4J3VRB (Bath Mat must survive unified edit)
# ---------------------------------------------------------------------------


PROD_BAG = "42EN4J3VRB"


def test_42EN4J3VRB_bath_mat_preserved_when_weight_edited(cur):
    """Regression: Bath Mat ×1 @ $4.00 must remain after weight-only unified edit."""
    from backend.rinse_bulk_workitems import create_workitem, save_bag_bulk_workitems

    # Seed day bag under the production bag id.
    cur.day_bags[(ORG, D1, PROD_BAG)] = {
        "organization_id": ORG,
        "shift_date_et": D1,
        "bag_id": PROD_BAG,
        "service_type": "WF",
        "rush_status": "NON-RUSH",
        "pre_weight_lbs": 12.0,
        "post_weight_lbs": 18.0,
        "weight_lbs": 18.0,
        "effective_status": "completed",
        "canonical_completion_employee": "Evelin",
        "canonical_completion_timestamp": datetime(2026, 7, 22, 14, 0, 0),
        "updated_at": datetime(2026, 7, 22, 6, 0, 0),
        "workload_entry_timestamp": datetime(2026, 7, 22, 9, 0, 0),
        "workload_entry_type": "scan",
    }
    bath = create_workitem(cur, ORG, name="Bath Mat", current_unit_price=4, display_order=10)
    seeded = save_bag_bulk_workitems(
        cur,
        ORG,
        shift_date_et=D1,
        bag_id=PROD_BAG,
        items=[{"workitem_id": bath["id"], "quantity": 1}],
        no_chargeable=False,
        reason="seed bath mat",
        actor_display_name="seed",
        allow_closed=True,
    )
    assert seeded.get("ok") is True

    out = apply_unified_bag_edit(
        cur,
        ORG,
        bag_id=PROD_BAG,
        selected_date_et=D1,
        reason="Production reproducer: change weight, keep Bath Mat",
        draft={
            "post_weight_lbs": 19.5,
            "bulk_items": [{"workitem_id": bath["id"], "quantity": 1}],
            "service_type": "WF",
            "rush_flag": "NON-RUSH",
        },
        outcome_action="keep_review",
        expected_updated_at="2026-07-22T06:00:00",
        actor_display_name="Manager Mo",
    )
    assert out["ok"] is True
    after = out["after"]
    assert after["post_weight_lbs"] == 19.5
    assert after["bulk_items"] == [
        {
            "workitem_id": bath["id"],
            "name": "Bath Mat",
            "quantity": 1,
            "unit_price": 4.0,
            "line_total": 4.0,
        }
    ]
    # Completed outcome is not wiped by keep_review field edits alone.
    assert cur.day_bags[(ORG, D1, PROD_BAG)]["effective_status"] == "completed"


def test_save_and_keep_in_review_is_atomic(cur):
    out = apply_unified_bag_edit(
        cur,
        ORG,
        bag_id=BAG,
        selected_date_et=D1,
        reason="atomic keep review",
        draft={"post_weight_lbs": 11.0, "rush_flag": "RUSH"},
        outcome_action="keep_review",
    )
    assert out["ok"] is True
    assert out["edit_id"]
    assert len(cur.tables["rinse_step1_bag_edits"]) == 1
    assert cur.day_bags[(ORG, D1, BAG)]["post_weight_lbs"] == 11.0


def test_save_and_mark_completed_is_atomic(cur):
    with patch(
        "backend.rinse_operator_manual_correction.apply_operator_approved_manual_completion",
        return_value={"ok": True, "status": "completed"},
    ) as mock_complete:
        out = apply_unified_bag_edit(
            cur,
            ORG,
            bag_id=BAG,
            selected_date_et=D1,
            reason="atomic mark completed",
            draft={
                "post_weight_lbs": 14.0,
                "completed_by": "Evelin",
                "completion_at": "2026-07-22T15:00:00",
            },
            outcome_action="mark_completed",
            actor_display_name="Manager Mo",
        )
    assert out["ok"] is True
    assert len(cur.tables["rinse_step1_bag_edits"]) == 1
    assert cur.day_bags[(ORG, D1, BAG)]["post_weight_lbs"] == 14.0
    mock_complete.assert_called_once()
    assert any(d["field_name"] == "outcome_action" for d in out["deltas"])


def test_undo_restores_bulk_weights_service_rush(cur):
    from backend.rinse_bulk_workitems import create_workitem

    bath = create_workitem(cur, ORG, name="Bath Mat", current_unit_price=4, display_order=10)
    first = apply_unified_bag_edit(
        cur,
        ORG,
        bag_id=BAG,
        selected_date_et=D1,
        reason="multi-field edit",
        draft={
            "service_type": "WF",
            "rush_flag": "RUSH",
            "pre_weight_lbs": 5.0,
            "post_weight_lbs": 15.0,
            "bulk_items": [{"workitem_id": bath["id"], "quantity": 1}],
        },
    )
    assert first["ok"] is True
    assert first["after"]["bulk_items"]
    undone = undo_bag_edit(cur, ORG, edit_id=first["edit_id"])
    assert undone["ok"] is True
    after = undone["after"]
    # Restored to fixture defaults: pre=10, post=None, rush=RUSH, empty bulk.
    assert after["pre_weight_lbs"] == 10.0
    assert after["post_weight_lbs"] is None
    assert after.get("bulk_items") in ([], None)
    assert cur.tables["rinse_bag_bulk_workitems"] == []
