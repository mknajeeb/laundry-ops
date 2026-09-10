"""WF Current Workload customer names + Pending manager controls."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.management_wf_cw_controls import (
    OVERRIDE_EXCLUDE,
    OVERRIDE_MANUAL_REVIEW,
    apply_cw_manager_overlay,
    clear_cw_override,
    public_cw_override_fields,
    upsert_cw_override,
)
from backend.rinse_veewash_workload import (
    OUTCOME_PENDING,
    OUTCOME_REVIEW_REQUIRED,
    REASON_MANAGER_SENT_FOR_REVIEW,
)
from backend.rinse_wf_current_workload import (
    REVIEW_REGISTRY_STALE_COMPLETED,
    get_current_wf_workload,
    get_selected_date_wf_completed,
)

ORG = 3
DAY = date(2026, 9, 10)


def test_apply_cw_overlay_moves_pending_to_manual_review():
    wl = {
        "pending": frozenset({"BAG1", "BAG2"}),
        "review": frozenset(),
        "open": frozenset({"BAG1", "BAG2"}),
        "counts": {"pending": 2, "review": 0, "open": 2},
        "items": [
            {
                "bag_id": "BAG1",
                "status": OUTCOME_PENDING,
                "review_reason_codes": [],
                "customer_name": "Pat",
            },
            {
                "bag_id": "BAG2",
                "status": OUTCOME_PENDING,
                "review_reason_codes": [],
                "customer_name": "Sam",
            },
        ],
    }
    overrides = {
        "BAG1": {
            "bag_id": "BAG1",
            "override_type": OVERRIDE_MANUAL_REVIEW,
            "active": True,
            "reason_code": REASON_MANAGER_SENT_FOR_REVIEW,
            "reason_text": "Missing item investigation",
            "actor_display_name": "Jennifer Manager",
            "created_at_et": datetime(2026, 9, 10, 12, 14),
        }
    }
    out = apply_cw_manager_overlay(wl, overrides)
    assert out["oi_counts"]["pending"] == 2
    assert out["counts"]["pending"] == 1
    assert out["counts"]["review"] == 1
    assert "BAG1" in out["review"]
    assert "BAG1" not in out["pending"]
    item = next(i for i in out["items"] if i["bag_id"] == "BAG1")
    assert item["status"] == OUTCOME_REVIEW_REQUIRED
    assert item["review_origin"] == "manual"
    assert item["sent_by"] == "Jennifer Manager"
    assert item["manual_review_reason"] == "Missing item investigation"
    assert REASON_MANAGER_SENT_FOR_REVIEW in item["review_reason_codes"]


def test_apply_cw_overlay_keeps_system_and_manual_distinct():
    wl = {
        "pending": frozenset(),
        "review": frozenset({"BAGB1"}),
        "open": frozenset({"BAGB1"}),
        "counts": {"pending": 0, "review": 1, "open": 1},
        "items": [
            {
                "bag_id": "BAGB1",
                "status": OUTCOME_REVIEW_REQUIRED,
                "review_reason_codes": [REVIEW_REGISTRY_STALE_COMPLETED],
            }
        ],
    }
    overrides = {
        "BAGB1": {
            "bag_id": "BAGB1",
            "override_type": OVERRIDE_MANUAL_REVIEW,
            "active": True,
            "reason_code": REASON_MANAGER_SENT_FOR_REVIEW,
            "reason_text": "Manager check",
            "actor_display_name": "Muhammad",
            "created_at_et": datetime(2026, 9, 10, 12, 14),
        }
    }
    out = apply_cw_manager_overlay(wl, overrides)
    item = out["items"][0]
    assert item["review_origin"] == "both"
    assert REVIEW_REGISTRY_STALE_COMPLETED in item["system_review_reason_codes"]
    assert item["manual_review_active"] is True


def test_apply_cw_overlay_soft_excludes_without_touching_oi_open():
    wl = {
        "pending": frozenset({"BAGC1", "BAGD1"}),
        "review": frozenset(),
        "open": frozenset({"BAGC1", "BAGD1"}),
        "counts": {"pending": 2, "review": 0, "open": 2},
        "items": [
            {"bag_id": "BAGC1", "status": OUTCOME_PENDING, "review_reason_codes": []},
            {"bag_id": "BAGD1", "status": OUTCOME_PENDING, "review_reason_codes": []},
        ],
    }
    overrides = {
        "BAGC1": {
            "bag_id": "BAGC1",
            "override_type": OVERRIDE_EXCLUDE,
            "active": True,
            "reason_code": "MANAGER_EXCLUDED_FROM_WORKLOAD",
            "reason_text": "Not this shift",
            "actor_display_name": "Manager",
            "created_at_et": datetime(2026, 9, 10, 9, 0),
        }
    }
    out = apply_cw_manager_overlay(wl, overrides)
    assert out["oi_open"] == frozenset({"BAGC1", "BAGD1"})
    assert out["counts"]["open"] == 1
    assert "BAGC1" not in {i["bag_id"] for i in out["items"]}
    assert "BAGC1" in out["excluded_from_workload"]


def test_resolve_manual_does_not_clear_system_review_in_overlay():
    wl = {
        "pending": frozenset(),
        "review": frozenset({"BAGE1"}),
        "open": frozenset({"BAGE1"}),
        "counts": {"pending": 0, "review": 1, "open": 1},
        "items": [
            {
                "bag_id": "BAGE1",
                "status": OUTCOME_REVIEW_REQUIRED,
                "review_reason_codes": [REVIEW_REGISTRY_STALE_COMPLETED],
            }
        ],
    }
    # No active manual override after resolve → system-only remains.
    out = apply_cw_manager_overlay(wl, {})
    item = out["items"][0]
    assert item["review_origin"] == "system"
    assert item["status"] == OUTCOME_REVIEW_REQUIRED
    assert REVIEW_REGISTRY_STALE_COMPLETED in item["review_reason_codes"]


def test_upsert_and_clear_cw_override_roundtrip():
    stored: dict = {}

    class Cur:
        def execute(self, sql, params=None):
            s = " ".join(str(sql).lower().split())
            if "create table" in s:
                return
            if "insert into" in s:
                stored["row"] = {
                    "organization_id": params[0],
                    "bag_id": params[1],
                    "override_type": params[2],
                    "active": 1,
                    "reason_code": params[3],
                    "reason_text": params[4],
                    "actor_user_id": params[5],
                    "actor_display_name": params[6],
                    "order_instance_id": params[7],
                    "created_at_et": params[8],
                }
                return
            if "update" in s and "active = 0" in s:
                if stored.get("row"):
                    stored["row"]["active"] = 0
                    stored["row"]["cleared_at_et"] = params[0]
                    stored["cleared"] = True
                self.rowcount = 1 if stored.get("row") else 0
                return
            if "select" in s:
                self._rows = [stored["row"]] if stored.get("row") and stored["row"].get("active") else []
                return
            self._rows = []

        def fetchall(self):
            return list(getattr(self, "_rows", []) or [])

        def fetchone(self):
            rows = self.fetchall()
            return rows[0] if rows else None

    cur = Cur()
    with patch("backend.management_wf_cw_controls.table_exists", return_value=True), patch(
        "backend.management_wf_cw_controls.invalidate_schema_cache", create=True
    ):
        out = upsert_cw_override(
            cur,
            ORG,
            bag_id="BAGF1",
            override_type=OVERRIDE_MANUAL_REVIEW,
            reason_text="Check bag",
            actor_user_id=7,
            actor_display_name="Manager A",
        )
    assert out["ok"] is True
    assert stored["row"]["override_type"] == OVERRIDE_MANUAL_REVIEW
    assert stored["row"]["reason_code"] == REASON_MANAGER_SENT_FOR_REVIEW

    with patch("backend.management_wf_cw_controls.table_exists", return_value=True):
        cleared = clear_cw_override(
            cur,
            ORG,
            bag_id="BAGF1",
            actor_display_name="Manager A",
            clear_reason_text="Done",
            only_types=[OVERRIDE_MANUAL_REVIEW],
        )
    assert cleared["ok"] is True
    assert stored["row"]["active"] == 0


def test_move_to_review_records_correction_without_scan_mutation():
    from backend.management_wf_cw_controls import move_pending_to_manual_review

    corrections = []
    class Cur:
        def execute(self, sql, params=None):
            s = " ".join(str(sql).lower().split())
            if "create table" in s or "insert into rinse_wf_cw" in s:
                return
            if "select" in s and "day_bags" in s:
                self._rows = []
                return
            self._rows = []

        def fetchall(self):
            return list(getattr(self, "_rows", []) or [])

    cur = Cur()
    with patch(
        "backend.management_wf_cw_controls.table_exists", return_value=True
    ), patch(
        "backend.rinse_veewash_step1_api._record_correction",
        side_effect=lambda *a, **k: corrections.append(k or a),
    ), patch(
        "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
        return_value=[],
    ), patch(
        "backend.rinse_veewash_step1_api._clear_management_today_after_specialty_mutation",
    ):
        out = move_pending_to_manual_review(
            cur,
            ORG,
            bag_id="BAGG1",
            reason_text="Missing item investigation",
            actor_user_id=9,
            actor_display_name="Muhammad",
            selected_date_et=DAY,
        )
    assert out["ok"] is True
    assert out["override_type"] == OVERRIDE_MANUAL_REVIEW
    assert out["day_bag_sync"]["synced"] is False
    assert corrections
    # No scan/OI mutation helpers invoked beyond override + audit.


def test_current_workload_bulk_resolves_customer_names_once():
    open_rows = [
        {
            "order_instance_id": 1,
            "bag_id": "BAGH1",
            "service_type": "WF",
            "cycle_anchor_at": datetime(2026, 9, 9, 10, 0),
            "completed_at": None,
        },
        {
            "order_instance_id": 2,
            "bag_id": "BAGI1",
            "service_type": "WF",
            "cycle_anchor_at": datetime(2026, 9, 9, 11, 0),
            "completed_at": None,
        },
    ]
    resolve_calls = []

    def fake_resolve(cursor, org, bags, selected_date_et=None):
        resolve_calls.append(list(bags))
        out = []
        for i, b in enumerate(bags):
            row = dict(b)
            row["customer_name"] = f"Customer {i + 1}" if i == 0 else None
            out.append(row)
        # emulate customer_name_or_unknown
        from backend.rinse_employee_productivity_sessions import customer_name_or_unknown

        for row in out:
            row["customer_name"] = customer_name_or_unknown(row.get("customer_name"))
        return out

    cur = MagicMock()
    with (
        patch(
            "backend.rinse_order_instances.list_open_wf_order_instances",
            return_value=open_rows,
        ),
        patch(
            "backend.rinse_wf_canonical_workload._authoritative_hd_bag_ids",
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_canonical_workload._review_wf_bag_ids_from_cycles",
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_current_workload.registry_stale_completion_review_bags",
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_current_workload.lifecycle_received_from_vendor_at",
            return_value=None,
        ),
        patch(
            "backend.rinse_employee_productivity_sessions.resolve_customer_names_for_bags",
            side_effect=fake_resolve,
        ),
        patch(
            "backend.management_wf_cw_controls.bulk_load_active_cw_overrides",
            return_value={},
        ),
    ):
        wl = get_current_wf_workload(cur, ORG, include_received_from_vendor=False)

    assert len(resolve_calls) == 1
    assert len(resolve_calls[0]) == 2
    names = {i["bag_id"]: i["customer_name"] for i in wl["items"]}
    assert names["BAGH1"] == "Customer 1"
    assert names["BAGI1"] == "Unknown Customer"
    assert wl["counts"]["pending"] == 2


def test_completed_bulk_resolves_customer_names_once():
    completed_rows = [
        {
            "order_instance_id": 9,
            "bag_id": "BAGJ1",
            "service_type": "WF",
            "cycle_anchor_at": datetime(2026, 9, 10, 8, 0),
            "completed_at": datetime(2026, 9, 10, 12, 0),
            "completion_source": "scan",
        }
    ]
    resolve_calls = []

    def fake_resolve(cursor, org, bags, selected_date_et=None):
        resolve_calls.append((selected_date_et, list(bags)))
        return [{**dict(b), "customer_name": "Completed Cust"} for b in bags]

    cur = MagicMock()
    with (
        patch(
            "backend.rinse_order_instances.list_order_instances_completed_on_date",
            return_value=completed_rows,
        ),
        patch(
            "backend.rinse_wf_canonical_workload._authoritative_hd_bag_ids",
            return_value=set(),
        ),
        patch(
            "backend.rinse_wf_current_workload.lifecycle_received_from_vendor_at",
            return_value=None,
        ),
        patch(
            "backend.rinse_employee_productivity_sessions.resolve_customer_names_for_bags",
            side_effect=fake_resolve,
        ),
    ):
        out = get_selected_date_wf_completed(cur, ORG, DAY)

    assert len(resolve_calls) == 1
    assert resolve_calls[0][0] == DAY
    assert out["items"][0]["customer_name"] == "Completed Cust"


def test_public_cw_override_fields_unknown_when_inactive():
    pub = public_cw_override_fields(None)
    assert pub["manual_review_active"] is False
    assert pub["excluded_from_workload"] is False
