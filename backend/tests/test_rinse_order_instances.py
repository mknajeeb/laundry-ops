"""Tests for rinse_order_instances — narrow order_instance_id spine."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from backend.rinse_order_instances import (
    bags_with_order_instance_covering_date,
    has_authoritative_new_order_boundary_after,
    is_authoritative_completed_cycle,
    is_current_order_instance_completed,
    should_create_new_order_instance_for_cycle,
    upsert_order_instance_from_cycle,
)
from backend.rinse_wf_canonical_workload import (
    LIFECYCLE_COMPLETED,
    LIFECYCLE_OPEN,
    _terminal_before_date,
    get_wf_bag_lifecycle,
)


ORG = 3


def test_authoritative_completed_cycle_requires_completed_stamp():
    assert is_authoritative_completed_cycle(
        {
            "status": "COMPLETED",
            "cycle_anchor_at": datetime(2026, 8, 24, 0, 28),
            "completed_at": datetime(2026, 8, 24, 16, 48),
        }
    )
    assert not is_authoritative_completed_cycle(
        {
            "status": "REVIEW",
            "cycle_anchor_at": datetime(2026, 8, 24, 3, 18),
            "completed_at": None,
        }
    )
    assert not is_authoritative_completed_cycle(
        {
            "status": "ACTIVE",
            "cycle_anchor_at": datetime(2026, 8, 28, 4, 44),
            "completed_at": None,
        }
    )


def _mock_instance_cursor(stored: dict, next_id: dict):
    def execute(sql, params=None):
        sql_l = " ".join(str(sql).lower().split())
        if "create table" in sql_l:
            return
        if sql_l.startswith("select * from rinse_order_instances where source_cycle_id"):
            cid = int(params[0])
            for row in stored.values():
                if row.get("source_cycle_id") == cid:
                    execute._result = [row]
                    return
            execute._result = []
            return
        if "from rinse_order_instances" in sql_l and "order by cycle_anchor_at" in sql_l:
            org = int(params[0])
            bag = str(params[1])
            svc = str(params[2]) if params is not None and len(params) > 2 else None
            rows = []
            for key, r in stored.items():
                o, b, s = key[0], key[1], key[2]
                if o == org and b == bag and (svc is None or s == svc):
                    rows.append(r)
            rows.sort(key=lambda r: (r["cycle_anchor_at"], r["order_instance_id"]))
            execute._result = rows
            return
        if (
            "select * from rinse_order_instances where organization_id" in sql_l
            and "cycle_anchor_at" in sql_l
            and params is not None
            and len(params) >= 4
        ):
            key = (int(params[0]), str(params[1]), str(params[2]), params[3])
            row = stored.get(key)
            execute._result = [row] if row else []
            return
        if sql_l.startswith("select * from rinse_order_instances where order_instance_id"):
            oid = int(params[0])
            for row in stored.values():
                if int(row["order_instance_id"]) == oid:
                    execute._result = [row]
                    return
            execute._result = []
            return
        if sql_l.startswith("insert into rinse_order_instances"):
            oid = next_id["n"]
            next_id["n"] += 1
            row = {
                "order_instance_id": oid,
                "organization_id": int(params[0]),
                "bag_id": params[1],
                "service_type": params[2],
                "cycle_anchor_at": params[3],
                "source_cycle_id": params[4],
                "completed_at": params[5],
                "completed_by_user_id": params[6],
                "completed_by_employee_name": params[7],
                "completion_source": params[8],
            }
            key = (
                row["organization_id"],
                row["bag_id"],
                row["service_type"],
                row["cycle_anchor_at"],
            )
            stored[key] = row
            execute.lastrowid = oid
            return
        if sql_l.startswith("update rinse_order_instances"):
            return
        execute._result = []

    cur = MagicMock()
    cur.execute.side_effect = execute
    cur.fetchone.side_effect = lambda: (
        execute._result[0] if getattr(execute, "_result", None) else None
    )
    cur.fetchall.side_effect = lambda: list(getattr(execute, "_result", []) or [])
    cur.lastrowid = None
    return cur


def test_cea4_two_completed_cycles_become_two_instances():
    """CEA4: cycle 89805 and 1840886 → distinct order instances with pickup boundary."""
    stored: dict[tuple, dict] = {}
    next_id = {"n": 1}
    cur = _mock_instance_cursor(stored, next_id)

    with patch("backend.rinse_order_instances.table_exists", return_value=True), patch(
        "backend.rinse_order_instances.ensure_rinse_order_instances_table"
    ), patch(
        "backend.rinse_order_instances.has_authoritative_new_order_boundary_after",
        side_effect=lambda *a, **k: True,
    ):
        a = upsert_order_instance_from_cycle(
            cur,
            ORG,
            {
                "id": 89805,
                "bag_id": "CEA4TAF6IK",
                "service_type": "WF",
                "status": "COMPLETED",
                "cycle_anchor_at": datetime(2026, 8, 24, 0, 28),
                "completed_at": datetime(2026, 8, 24, 16, 48),
                "completion_source": "post_garments_reviewed_weight_entry",
            },
            completed_by_employee_name="Jennifer (VeeWash)",
        )
        b = upsert_order_instance_from_cycle(
            cur,
            ORG,
            {
                "id": 1840886,
                "bag_id": "CEA4TAF6IK",
                "service_type": "WF",
                "status": "COMPLETED",
                "cycle_anchor_at": datetime(2026, 8, 28, 6, 31),
                "completed_at": datetime(2026, 8, 28, 9, 14),
                "completion_source": "post_garments_reviewed_weight_entry",
            },
            completed_by_employee_name="Veewash (Training Account 2)",
        )
        a2 = upsert_order_instance_from_cycle(
            cur,
            ORG,
            {
                "id": 89805,
                "bag_id": "CEA4TAF6IK",
                "service_type": "WF",
                "status": "COMPLETED",
                "cycle_anchor_at": datetime(2026, 8, 24, 0, 28),
                "completed_at": datetime(2026, 8, 24, 16, 48),
            },
        )

    assert a is not None and b is not None
    assert int(a["order_instance_id"]) != int(b["order_instance_id"])
    assert a["bag_id"] == b["bag_id"] == "CEA4TAF6IK"
    assert a2 is not None
    assert int(a2["order_instance_id"]) == int(a["order_instance_id"])
    assert len(stored) == 2


def test_44n8_malformed_aug28_anchor_does_not_create_second_instance():
    """44N8: Aug27 completion + Aug28 cycle_anchor without new pickup → one instance."""
    stored: dict[tuple, dict] = {}
    next_id = {"n": 1}
    cur = _mock_instance_cursor(stored, next_id)

    with patch("backend.rinse_order_instances.table_exists", return_value=True), patch(
        "backend.rinse_order_instances.ensure_rinse_order_instances_table"
    ), patch(
        "backend.rinse_order_instances.has_authoritative_new_order_boundary_after",
        return_value=False,
    ):
        a = upsert_order_instance_from_cycle(
            cur,
            ORG,
            {
                "id": 1589747,
                "bag_id": "44N8W174KG",
                "service_type": "WF",
                "status": "COMPLETED",
                "cycle_anchor_at": datetime(2026, 8, 28, 3, 12, 49),
                "completed_at": datetime(2026, 8, 27, 15, 50),
                "completion_source": "manager_correct_completion",
            },
        )
        # Simulate a second completed cycle with later anchor but no new-order boundary.
        b = upsert_order_instance_from_cycle(
            cur,
            ORG,
            {
                "id": 9999999,
                "bag_id": "44N8W174KG",
                "service_type": "WF",
                "status": "COMPLETED",
                "cycle_anchor_at": datetime(2026, 8, 28, 4, 0),
                "completed_at": datetime(2026, 8, 27, 15, 50),
                "completion_source": "manager_correct_completion",
            },
        )

    assert a is not None and b is not None
    assert int(a["order_instance_id"]) == int(b["order_instance_id"])
    assert len(stored) == 1


def test_should_create_requires_boundary_after_prior_completion():
    cur = MagicMock()
    cycle = {
        "status": "COMPLETED",
        "cycle_anchor_at": datetime(2026, 8, 28, 6, 31),
        "completed_at": datetime(2026, 8, 28, 9, 14),
    }
    with patch(
        "backend.rinse_order_instances.has_authoritative_new_order_boundary_after",
        return_value=False,
    ):
        assert not should_create_new_order_instance_for_cycle(
            cur,
            ORG,
            "44N8W174KG",
            cycle,
            prior_completed_at=datetime(2026, 8, 27, 15, 50),
        )
    with patch(
        "backend.rinse_order_instances.has_authoritative_new_order_boundary_after",
        return_value=True,
    ):
        assert should_create_new_order_instance_for_cycle(
            cur,
            ORG,
            "CEA4TAF6IK",
            cycle,
            prior_completed_at=datetime(2026, 8, 24, 16, 48),
        )
    assert should_create_new_order_instance_for_cycle(
        cur, ORG, "NEWBAG", cycle, prior_completed_at=None
    )


def test_new_order_boundary_detects_pickup_after_prior():
    cur = MagicMock()
    with patch(
        "backend.rinse_order_instances.load_new_order_boundary_timestamps",
        return_value=[
            datetime(2026, 8, 23, 20, 4),
            datetime(2026, 8, 27, 21, 19),
        ],
    ):
        assert has_authoritative_new_order_boundary_after(
            cur,
            ORG,
            "CEA4TAF6IK",
            datetime(2026, 8, 24, 16, 48),
            before_or_at=datetime(2026, 8, 28, 9, 14),
        )
        assert not has_authoritative_new_order_boundary_after(
            cur,
            ORG,
            "CEA4TAF6IK",
            datetime(2026, 8, 28, 10, 0),
            before_or_at=datetime(2026, 8, 28, 12, 0),
        )


def test_terminal_before_carves_out_covering_instance():
    """Prior registry completion must not block a later order instance on D."""
    cur = MagicMock()
    with patch(
        "backend.rinse_wf_canonical_workload._registry_completed_date_by_bag",
        return_value={"CEA4TAF6IK": date(2026, 8, 24)},
    ), patch(
        "backend.rinse_order_instances.bags_with_order_instance_covering_date",
        return_value={"CEA4TAF6IK"},
    ), patch(
        "backend.rinse_veewash_day_membership._bags_canonically_completed_before_opening",
        return_value=set(),
    ):
        terminal = _terminal_before_date(
            cur, ORG, date(2026, 8, 28), ["CEA4TAF6IK", "OTHER"]
        )
    assert "CEA4TAF6IK" not in terminal


def test_terminal_before_keeps_true_historical_terminal():
    cur = MagicMock()
    with patch(
        "backend.rinse_wf_canonical_workload._registry_completed_date_by_bag",
        return_value={"OLD1": date(2026, 8, 20)},
    ), patch(
        "backend.rinse_order_instances.bags_with_order_instance_covering_date",
        return_value=set(),
    ), patch(
        "backend.rinse_veewash_day_membership._bags_canonically_completed_before_opening",
        return_value=set(),
    ):
        terminal = _terminal_before_date(cur, ORG, date(2026, 8, 28), ["OLD1"])
    assert terminal == {"OLD1"}


def test_current_instance_completed_uses_latest_instance():
    cur = MagicMock()
    with patch(
        "backend.rinse_order_instances.get_latest_order_instance_for_bag",
        return_value={
            "order_instance_id": 2,
            "completed_at": datetime(2026, 8, 28, 9, 14),
        },
    ):
        assert is_current_order_instance_completed(cur, ORG, "CEA4TAF6IK") is True
    with patch(
        "backend.rinse_order_instances.get_latest_order_instance_for_bag",
        return_value={
            "order_instance_id": 2,
            "completed_at": None,
        },
    ):
        assert is_current_order_instance_completed(cur, ORG, "CEA4TAF6IK") is False


def test_lifecycle_open_when_latest_instance_incomplete():
    cur = MagicMock()
    with patch(
        "backend.rinse_order_instances.get_latest_order_instance_for_bag",
        return_value={
            "order_instance_id": 9,
            "completed_at": None,
            "cycle_anchor_at": datetime(2026, 8, 28, 6, 31),
        },
    ):
        life = get_wf_bag_lifecycle(cur, ORG, "CEA4TAF6IK")
    assert life["lifecycle"] == LIFECYCLE_OPEN


def test_lifecycle_falls_back_to_registry_when_no_instances():
    cur = MagicMock()
    with patch(
        "backend.rinse_order_instances.get_latest_order_instance_for_bag",
        return_value=None,
    ), patch(
        "backend.rinse_bag_registry.get_registry_row",
        return_value={
            "completion_status": "COMPLETED",
            "completed_at": datetime(2026, 8, 20, 12, 0),
        },
    ):
        life = get_wf_bag_lifecycle(cur, ORG, "BAG1")
    assert life["lifecycle"] == LIFECYCLE_COMPLETED


def test_covering_date_completed_on_d_not_prior_anchor_only():
    """CEA4 Aug28 covers via completed_at; 44N8 Aug27 completed + Aug28 anchor does not."""
    cur = MagicMock()
    cur.fetchall.return_value = [
        {
            "bag_id": "CEA4TAF6IK",
            "cycle_anchor_at": datetime(2026, 8, 28, 6, 31),
            "completed_at": datetime(2026, 8, 28, 9, 14),
        },
        {
            "bag_id": "44N8W174KG",
            "cycle_anchor_at": datetime(2026, 8, 28, 3, 12, 49),
            "completed_at": datetime(2026, 8, 27, 15, 50),
        },
        {
            "bag_id": "OTHER",
            "cycle_anchor_at": datetime(2026, 8, 24, 0, 28),
            "completed_at": datetime(2026, 8, 24, 16, 48),
        },
    ]
    with patch("backend.rinse_order_instances.ensure_rinse_order_instances_table"):
        covering = bags_with_order_instance_covering_date(
            cur, ORG, date(2026, 8, 28), ["CEA4TAF6IK", "44N8W174KG", "OTHER"]
        )
    assert covering == {"CEA4TAF6IK"}
    assert "44N8W174KG" not in covering


def test_ensure_open_oi_after_completed_requires_boundary():
    from backend.rinse_order_instances import ensure_open_order_instance_for_new_active_cycle

    prior = {
        "order_instance_id": 1,
        "bag_id": "BAGNEW1",
        "service_type": "WF",
        "cycle_anchor_at": datetime(2026, 8, 20, 1, 0),
        "completed_at": datetime(2026, 8, 20, 15, 0),
    }
    active = {
        "id": 99,
        "bag_id": "BAGNEW1",
        "service_type": "WF",
        "status": "ACTIVE",
        "cycle_anchor_at": datetime(2026, 8, 30, 22, 0),
        "completed_at": None,
    }
    cur = MagicMock()
    with patch(
        "backend.rinse_order_instances.get_order_instance_by_cycle_key",
        return_value=None,
    ), patch(
        "backend.rinse_order_instances.get_latest_order_instance_for_bag",
        return_value=prior,
    ), patch(
        "backend.rinse_order_instances.has_authoritative_new_order_boundary_after",
        return_value=False,
    ) as boundary, patch(
        "backend.rinse_order_instances.upsert_order_instance_from_cycle",
    ) as upsert:
        out = ensure_open_order_instance_for_new_active_cycle(cur, ORG, active)
    assert out is None
    upsert.assert_not_called()
    boundary.assert_called_once()


def test_ensure_open_oi_creates_when_boundary_after_prior_completion():
    from backend.rinse_order_instances import ensure_open_order_instance_for_new_active_cycle

    prior = {
        "order_instance_id": 1,
        "bag_id": "BAGNEW2",
        "service_type": "WF",
        "cycle_anchor_at": datetime(2026, 8, 20, 1, 0),
        "completed_at": datetime(2026, 8, 20, 15, 0),
    }
    active = {
        "id": 100,
        "bag_id": "BAGNEW2",
        "service_type": "WF",
        "status": "ACTIVE",
        "cycle_anchor_at": datetime(2026, 8, 30, 22, 0),
        "completed_at": None,
    }
    created = {**active, "order_instance_id": 55, "completed_at": None}
    cur = MagicMock()
    with patch(
        "backend.rinse_order_instances.get_order_instance_by_cycle_key",
        return_value=None,
    ), patch(
        "backend.rinse_order_instances.get_latest_order_instance_for_bag",
        return_value=prior,
    ), patch(
        "backend.rinse_order_instances.has_authoritative_new_order_boundary_after",
        return_value=True,
    ), patch(
        "backend.rinse_order_instances.upsert_order_instance_from_cycle",
        return_value=created,
    ) as upsert:
        out = ensure_open_order_instance_for_new_active_cycle(cur, ORG, active)
    assert out is created
    upsert.assert_called_once()


def test_ship_window_open_oi_outside_window_not_missing_from_portal():
    """Open OI outside rolling STV window must not become Missing From Portal."""
    from datetime import datetime

    from backend.rinse_wf_canonical_workload import get_canonical_wf_workload

    day = date(2026, 8, 31)
    cur = MagicMock()
    open_row = {
        "order_instance_id": 1,
        "bag_id": "OUTS1",
        "service_type": "WF",
        "cycle_anchor_at": datetime(2026, 8, 25, 10, 0),
        "completed_at": None,
    }
    with patch(
        "backend.rinse_order_instances.list_open_wf_order_instances",
        return_value=[open_row],
    ), patch(
        "backend.rinse_order_instances.list_order_instances_completed_on_date",
        return_value=[],
    ), patch(
        "backend.rinse_wf_canonical_workload._terminal_before_date",
        return_value=set(),
    ), patch(
        "backend.rinse_wf_canonical_workload._authoritative_hd_bag_ids",
        return_value=set(),
    ), patch(
        "backend.rinse_wf_canonical_workload._completion_date_on_d",
        return_value={},
    ), patch(
        "backend.rinse_wf_canonical_workload._review_wf_bag_ids_from_cycles",
        return_value=set(),
    ):
        wl = get_canonical_wf_workload(cur, ORG, day)
    assert "OUTS1" in (wl.get("bag_ids") or frozenset())
    assert "OUTS1" not in (wl.get("missing_from_portal") or frozenset())
    assert int((wl.get("counts") or {}).get("missing_from_portal") or 0) == 0
