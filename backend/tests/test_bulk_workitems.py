"""WF Bulk Workitem Review — classification, totals, and maintenance rules."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.rinse_bulk_workitems import (
    REASON_WF_BULK_WORKITEM_REVIEW,
    RESOLUTION_ITEMS,
    RESOLUTION_NO_CHARGE,
    _money,
    bag_bulk_review_cleared,
    purpose_is_bulk_workitem,
)
from backend.rinse_veewash_review import expand_review_required
from backend.rinse_veewash_workload import (
    REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY,
    REASON_WF_ZERO_OR_MISSING_POST_WEIGHT,
    classify_veewash_workload,
)


D1 = date(2026, 7, 22)


def _pres(service="WF", rush="RUSH"):
    return {
        "active": 1,
        "service_type": service,
        "rush_flag": rush,
        "portal_status": "at_vendor",
        "customer_name": "Test",
    }


def _entry(d=D1):
    return {
        "first_entry_at": datetime(d.year, d.month, d.day, 6, 0),
        "entry_date": d,
        "entry_source": "facility_dirty_scan",
    }


def test_purpose_markers():
    assert purpose_is_bulk_workitem("create-workitem-bulk")
    assert purpose_is_bulk_workitem("create-workitem-bulk Last Scan")
    assert purpose_is_bulk_workitem("create-bulk-workitem")
    assert not purpose_is_bulk_workitem("weight-entry")


def test_wf_bulk_scan_enters_review():
    presence = {"BAGWF1": _pres("WF")}
    entry = {"BAGWF1": _entry()}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={},
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        bulk_scan_by_bag={
            "BAGWF1": {
                "count": 1,
                "first_at": datetime(2026, 7, 22, 9, 0),
                "employee": "Maria",
            }
        },
    )
    assert "BAGWF1" in out["review_required"]
    assert REASON_WF_BULK_WORKITEM_REVIEW in (out["review_reasons_by_bag"].get("BAGWF1") or [])
    assert out["counts"]["review_required"] == 1


def test_hd_same_day_wia_with_bulk_stays_hd_not_wf_bulk_review():
    """Hang Dry has workitems-added + create-workitem-bulk; bulk does not redefine service."""
    presence = {"BAGHD1": _pres("HD")}
    entry = {"BAGHD1": _entry()}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={},
    )
    if "BAGHD1" not in (raw.get("new_today") or []) and "BAGHD1" not in (raw.get("carryover") or []):
        raw.setdefault("new_today", []).append("BAGHD1")
        raw.setdefault("rows", []).append(
            {"bag_id": "BAGHD1", "service_type": "HD", "outcome": "pending", "rush_flag": "RUSH"}
        )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        wia_by_bag={
            "BAGHD1": {
                "first_entry_at": datetime(2026, 7, 22, 7, 0),
                "entry_date": D1,
                "entry_source": "workitems-added",
            }
        },
        bulk_scan_by_bag={
            "BAGHD1": {"count": 1, "first_at": datetime(2026, 7, 22, 7, 0), "employee": "Maria"}
        },
        registry_service_by_bag={"BAGHD1": "HD"},
    )
    reasons = out.get("review_reasons_by_bag") or {}
    assert REASON_WF_BULK_WORKITEM_REVIEW not in (reasons.get("BAGHD1") or [])
    row = next(r for r in out["rows"] if r["bag_id"] == "BAGHD1")
    assert row["service_type"] == "HD"


def test_hd_with_wia_and_bulk_stays_hd_even_if_wia_prior_day():
    """Any workitems-added means Hang Dry pattern — prior-day WIA still keeps HD."""
    presence = {"BAGHD2": _pres("HD")}
    entry = {"BAGHD2": _entry()}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={},
    )
    if "BAGHD2" not in (raw.get("new_today") or []) and "BAGHD2" not in (raw.get("carryover") or []):
        raw.setdefault("new_today", []).append("BAGHD2")
        raw.setdefault("rows", []).append(
            {"bag_id": "BAGHD2", "service_type": "HD", "outcome": "pending", "rush_flag": "RUSH"}
        )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        wia_by_bag={
            "BAGHD2": {
                "first_entry_at": datetime(2026, 7, 21, 20, 0),
                "entry_date": date(2026, 7, 21),
                "entry_source": "workitems-added",
            }
        },
        bulk_scan_by_bag={
            "BAGHD2": {"count": 1, "first_at": datetime(2026, 7, 22, 6, 54), "employee": "Francis"}
        },
        registry_service_by_bag={"BAGHD2": "HD"},
    )
    reasons = out.get("review_reasons_by_bag") or {}
    assert REASON_WF_BULK_WORKITEM_REVIEW not in (reasons.get("BAGHD2") or [])
    row = next(r for r in out["rows"] if r["bag_id"] == "BAGHD2")
    assert row["service_type"] == "HD"


def test_portal_hd_bulk_without_wia_remaps_to_wf_review():
    """WF with work items: create-workitem-bulk only (no workitems-added) → WF + bulk review."""
    presence = {"BAGBULK1": _pres("HD")}
    entry = {"BAGBULK1": _entry()}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={},
    )
    if "BAGBULK1" not in (raw.get("new_today") or []) and "BAGBULK1" not in (raw.get("carryover") or []):
        raw.setdefault("new_today", []).append("BAGBULK1")
        raw.setdefault("rows", []).append(
            {
                "bag_id": "BAGBULK1",
                "service_type": "HD",
                "outcome": "pending",
                "rush_flag": "RUSH",
            }
        )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        wia_by_bag={},
        bulk_scan_by_bag={
            "BAGBULK1": {
                "count": 1,
                "first_at": datetime(2026, 7, 22, 6, 54),
                "employee": "Francis",
            }
        },
        registry_service_by_bag={"BAGBULK1": "HD"},
    )
    reasons = out.get("review_reasons_by_bag") or {}
    assert REASON_WF_BULK_WORKITEM_REVIEW in (reasons.get("BAGBULK1") or [])
    row = next(r for r in out["rows"] if r["bag_id"] == "BAGBULK1")
    assert row["service_type"] == "WF"


def test_zipvan_entry_does_not_force_hd_to_wf():
    """Facility entry rack is membership only — HD stays HD without bulk remap signals."""
    presence = {"ZIPHD1": _pres("HD", rush="RUSH")}
    entry = {
        "ZIPHD1": {
            "first_entry_at": datetime(2026, 7, 22, 6, 5),
            "entry_date": D1,
            "entry_source": "facility_dirty_scan",
        }
    }
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={},
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        wia_by_bag={
            "ZIPHD1": {
                "first_entry_at": datetime(2026, 7, 22, 7, 26),
                "entry_date": D1,
                "entry_source": "workitems-added",
            }
        },
        registry_service_by_bag={"ZIPHD1": "HD"},
    )
    row = next(r for r in out["rows"] if r["bag_id"] == "ZIPHD1")
    assert row["service_type"] == "HD"
    assert "ZIPHD1" in out["new_today"]


def test_multiple_bulk_scans_one_review_count():
    presence = {"BAGWF2": _pres("WF")}
    entry = {"BAGWF2": _entry()}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={},
    )
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        bulk_scan_by_bag={
            "BAGWF2": {
                "count": 3,
                "first_at": datetime(2026, 7, 22, 8, 0),
                "last_at": datetime(2026, 7, 22, 10, 0),
                "employee": "A",
            }
        },
    )
    assert out["review_required"].count("BAGWF2") == 1
    assert out["counts"]["review_required"] == 1


def test_saving_items_clears_only_bulk_reason():
    presence = {"BAGWF3": _pres("WF")}
    entry = {"BAGWF3": _entry()}
    raw = classify_veewash_workload(
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag=entry,
        completion_by_bag={
            "BAGWF3": {
                "completion_at": datetime(2026, 7, 22, 12, 0),
                "completion_date": D1,
                "completed_by": "Maria",
                "completion_source": "evaluate_bag_completion_v2:clean-rack",
            }
        },
    )
    # Force CWO + weight + bulk
    out = expand_review_required(
        raw,
        selected_date_et=D1,
        presence_by_bag=presence,
        entry_by_bag={},  # CWO
        weight_by_bag={"BAGWF3": {"pre_weight_lbs": 10.0, "post_weight_lbs": None}},
        bulk_scan_by_bag={"BAGWF3": {"count": 1, "first_at": datetime(2026, 7, 22, 9, 0)}},
        bulk_resolution_by_bag={
            "BAGWF3": {"resolution_type": RESOLUTION_ITEMS, "items_total": 8}
        },
        bulk_lines_by_bag={
            "BAGWF3": [
                {
                    "workitem_id": 1,
                    "workitem_name": "Bath Mat",
                    "unit_price": 4.0,
                    "quantity": 2,
                    "line_total": 8.0,
                }
            ]
        },
    )
    codes = out["review_reasons_by_bag"].get("BAGWF3") or []
    assert REASON_WF_BULK_WORKITEM_REVIEW not in codes
    assert REASON_COMPLETED_WITHOUT_RECOGNIZED_ENTRY in codes
    assert REASON_WF_ZERO_OR_MISSING_POST_WEIGHT in codes
    assert "BAGWF3" in out["review_required"]


def test_line_totals_money():
    assert _money(4) * 2 == Decimal("8.00")
    assert float(_money(Decimal("18.00") * 1)) == 18.0


def test_no_charge_requires_reason_clearing():
    assert bag_bulk_review_cleared(
        {"resolution_type": RESOLUTION_NO_CHARGE, "no_charge_reason": "False alarm"},
        [],
    )
    assert not bag_bulk_review_cleared(
        {"resolution_type": RESOLUTION_NO_CHARGE, "no_charge_reason": ""},
        [],
    )
    assert not bag_bulk_review_cleared(
        {"resolution_type": RESOLUTION_NO_CHARGE, "no_charge_reason": None},
        [],
    )


def test_items_resolution_needs_qty():
    assert bag_bulk_review_cleared(
        {"resolution_type": RESOLUTION_ITEMS},
        [{"quantity": 1, "line_total": 4}],
    )
    assert not bag_bulk_review_cleared(
        {"resolution_type": RESOLUTION_ITEMS},
        [{"quantity": 0, "line_total": 0}],
    )


class _FakeCursor:
    """Minimal cursor for maintenance CRUD tests."""

    def __init__(self):
        self.tables = {
            "rinse_bulk_workitems": [],
            "rinse_bag_bulk_workitems": [],
            "rinse_bag_bulk_workitem_resolutions": [],
            "rinse_bag_bulk_workitem_audits": [],
        }
        self._id = 1
        self.lastrowid = 0
        self._result = []
        self.connection = SimpleNamespace(commit=lambda: None)

    def execute(self, sql, params=None):
        params = params or ()
        s = " ".join(str(sql).split()).lower()
        if "information_schema" in s or "show tables" in s:
            self._result = [{"c": 1}]
            return
        if s.startswith("create table"):
            self._result = []
            return
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
        if s.startswith("update rinse_bulk_workitems"):
            nm, price, order, active, uid, uname, org, wid = params
            for r in self.tables["rinse_bulk_workitems"]:
                if r["organization_id"] == int(org) and r["id"] == int(wid):
                    r.update(
                        {
                            "name": nm,
                            "current_unit_price": price,
                            "display_order": int(order),
                            "active": int(active),
                            "updated_by_user_id": uid,
                            "updated_by_display_name": uname,
                        }
                    )
            self._result = []
            return
        if "from rinse_bag_bulk_workitems" in s and "count(*)" in s:
            org, wid = int(params[0]), int(params[1])
            c = sum(
                1
                for r in self.tables["rinse_bag_bulk_workitems"]
                if r["organization_id"] == org and r.get("workitem_id") == wid
            )
            self._result = [{"c": c}]
            return
        if s.startswith("delete from rinse_bulk_workitems"):
            org, wid = int(params[0]), int(params[1])
            self.tables["rinse_bulk_workitems"] = [
                r
                for r in self.tables["rinse_bulk_workitems"]
                if not (r["organization_id"] == org and r["id"] == wid)
            ]
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
                if not (
                    r["organization_id"] == org
                    and r["shift_date_et"] == day
                    and r["bag_id"] == bag
                )
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
        if "from rinse_cleaner_ticket_presence" in s:
            self._result = []
            return
        if s.startswith("insert into rinse_bag_bulk_workitem_resolutions"):
            # upsert simplified
            org, day, bag = int(params[0]), params[1], params[2]
            self.tables["rinse_bag_bulk_workitem_resolutions"] = [
                r
                for r in self.tables["rinse_bag_bulk_workitem_resolutions"]
                if not (
                    r["organization_id"] == org
                    and r["shift_date_et"] == day
                    and r["bag_id"] == bag
                )
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


def test_inactive_cannot_add_and_used_cannot_delete(monkeypatch):
    from backend import rinse_bulk_workitems as mod

    cur = _FakeCursor()
    monkeypatch.setattr(mod, "table_exists", lambda c, t: True)
    monkeypatch.setattr(
        mod,
        "get_day_record",
        lambda *a, **k: {"status": "OPEN"},
        raising=False,
    )
    # Patch imported get_day_record inside save via module path used at call time
    import backend.rinse_veewash_shift_day as shift_day

    monkeypatch.setattr(shift_day, "get_day_record", lambda *a, **k: {"status": "OPEN"})

    bath = mod.create_workitem(cur, 3, name="Bath Mat", current_unit_price=4, display_order=10)
    comfort = mod.create_workitem(cur, 3, name="Comforter", current_unit_price=18, display_order=20)
    assert bath["active"] is True

    # Deactivate comforter — cannot newly add
    mod.update_workitem(cur, 3, comfort["id"], active=False)
    out = mod.save_bag_bulk_workitems(
        cur,
        3,
        shift_date_et=D1,
        bag_id="BAGX",
        items=[{"workitem_id": comfort["id"], "quantity": 1}],
        reason="test",
        actor_display_name="Mgr",
    )
    assert out["ok"] is False
    assert out["error"] == "inactive_workitem_cannot_add"

    # Save bath mat
    out = mod.save_bag_bulk_workitems(
        cur,
        3,
        shift_date_et=D1,
        bag_id="BAGX",
        items=[{"workitem_id": bath["id"], "quantity": 2}],
        reason="customer has mats",
        actor_display_name="Mgr",
    )
    assert out["ok"] is True
    assert out["total"] == 8.0

    # Used workitem cannot delete
    with pytest.raises(ValueError, match="workitem_in_use_cannot_delete"):
        mod.delete_workitem(cur, 3, bath["id"])

    # Unused inactive can delete
    mod.delete_workitem(cur, 3, comfort["id"])


def test_price_change_does_not_change_historical(monkeypatch):
    from backend import rinse_bulk_workitems as mod
    import backend.rinse_veewash_shift_day as shift_day

    cur = _FakeCursor()
    monkeypatch.setattr(mod, "table_exists", lambda c, t: True)
    monkeypatch.setattr(shift_day, "get_day_record", lambda *a, **k: {"status": "OPEN"})

    bath = mod.create_workitem(cur, 3, name="Bath Mat", current_unit_price=4)
    mod.save_bag_bulk_workitems(
        cur,
        3,
        shift_date_et=D1,
        bag_id="BAGY",
        items=[{"workitem_id": bath["id"], "quantity": 2}],
        reason="ok",
    )
    mod.update_workitem(cur, 3, bath["id"], current_unit_price=9)
    lines = mod.load_bag_bulk_lines(cur, 3, D1, ["BAGY"])["BAGY"]
    assert lines[0]["unit_price"] == 4.0
    assert lines[0]["line_total"] == 8.0

    rev = mod.build_bulk_revenue_rows(cur, 3, shift_date_et=D1)
    assert rev[0]["unit_price"] == 4.0
    assert rev[0]["line_total"] == 8.0
    assert rev[0]["quantity"] == 2


def test_closed_shift_blocks_edit(monkeypatch):
    from backend import rinse_bulk_workitems as mod
    import backend.rinse_veewash_shift_day as shift_day

    cur = _FakeCursor()
    monkeypatch.setattr(mod, "table_exists", lambda c, t: True)
    monkeypatch.setattr(shift_day, "get_day_record", lambda *a, **k: {"status": "CLOSED"})
    bath = mod.create_workitem(cur, 3, name="Bath Mat", current_unit_price=4)
    out = mod.save_bag_bulk_workitems(
        cur,
        3,
        shift_date_et=D1,
        bag_id="BAGZ",
        items=[{"workitem_id": bath["id"], "quantity": 1}],
        reason="x",
    )
    assert out["error"] == "shift_closed_reopen_required"

    monkeypatch.setattr(shift_day, "get_day_record", lambda *a, **k: {"status": "REOPENED"})
    out2 = mod.save_bag_bulk_workitems(
        cur,
        3,
        shift_date_et=D1,
        bag_id="BAGZ",
        items=[{"workitem_id": bath["id"], "quantity": 1}],
        reason="reopened edit",
    )
    assert out2["ok"] is True


def test_no_charge_requires_reason_on_save(monkeypatch):
    from backend import rinse_bulk_workitems as mod
    import backend.rinse_veewash_shift_day as shift_day

    cur = _FakeCursor()
    monkeypatch.setattr(mod, "table_exists", lambda c, t: True)
    monkeypatch.setattr(shift_day, "get_day_record", lambda *a, **k: {"status": "OPEN"})
    out = mod.save_bag_bulk_workitems(
        cur,
        3,
        shift_date_et=D1,
        bag_id="BAGN",
        items=[],
        no_chargeable=True,
        no_charge_reason="",
    )
    assert out["error"] == "no_charge_reason_required"
    out2 = mod.save_bag_bulk_workitems(
        cur,
        3,
        shift_date_et=D1,
        bag_id="BAGN",
        items=[],
        no_chargeable=True,
        no_charge_reason="False alarm",
    )
    assert out2["ok"] is True
    assert out2["resolution_type"] == RESOLUTION_NO_CHARGE
