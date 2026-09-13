"""Management Issues Phase 1 — unit tests (mocked cursor, no live DB)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.management_issues import (
    MATCHED,
    UNMATCHED,
    _period_bounds,
    _rate,
    build_order_context,
    create_issue,
    dashboard_by_employee,
    dashboard_by_issue,
    ensure_mgmt_issues_tables,
    list_taxonomy,
    search_issue_bags,
    seed_mgmt_issue_taxonomy,
)
from backend.management_today import CountingCursor


class FakeCursor:
    """Minimal dictionary cursor with scripted fetch responses."""

    def __init__(self, script=None):
        self.script = list(script or [])
        self.executed = []
        self.lastrowid = 1
        self._fetch = None
        self._fetchall = []
        self.query_count = 0

    def execute(self, sql, params=None):
        self.query_count += 1
        self.executed.append((sql, params))
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, tuple):
                self._fetch, self._fetchall = item
            elif isinstance(item, list):
                self._fetch = item[0] if item else None
                self._fetchall = item
            elif isinstance(item, dict) or item is None:
                self._fetch = item
                self._fetchall = [item] if item else []
            else:
                self._fetch = None
                self._fetchall = []
        return self

    def fetchone(self):
        return self._fetch

    def fetchall(self):
        return list(self._fetchall or [])


def test_period_bounds_and_rate():
    # Freeze via monkeypatch business_today inside _period_bounds usage
    with patch("backend.management_issues.business_today", return_value=date(2026, 9, 13)):
        start, end, ps, pe = _period_bounds("30d")
        assert end == date(2026, 9, 13)
        assert start == date(2026, 8, 15)
        assert (end - start).days + 1 == (pe - ps).days + 1
    assert _rate(12, 100) == 12.0
    assert _rate(5, 0) is None


def test_ensure_and_seed_taxonomy():
    cur = MagicMock()
    # table_exists returns False then True after create
    with patch("backend.management_issues.table_exists", return_value=False):
        ensure_mgmt_issues_tables(cur)
    assert cur.execute.call_count >= 4

    cur2 = MagicMock()
    cur2.fetchone.return_value = None
    with patch("backend.management_issues.table_exists", return_value=True):
        with patch("backend.management_issues._ENSURED", set()):
            seed_mgmt_issue_taxonomy(cur2, 3)
    assert cur2.execute.call_count >= len(
        __import__("backend.management_issues", fromlist=["CATEGORY_SEEDS"]).CATEGORY_SEEDS
    )


def test_search_exact_and_multi_oi():
    from backend.rinse_order_instances import ORDER_INSTANCES_TABLE

    rows = [
        {
            "order_instance_id": 4951,
            "bag_id": "A347CPMO70",
            "service_type": "WF",
            "completed_at": datetime(2026, 9, 12, 19, 44, 0),
            "cycle_anchor_at": datetime(2026, 9, 11, 12, 0, 0),
            "name_clean": "Max Rodriguez",
            "rush_status": "0",
        },
        {
            "order_instance_id": 4800,
            "bag_id": "A347CPMO70",
            "service_type": "WF",
            "completed_at": datetime(2026, 8, 1, 15, 0, 0),
            "cycle_anchor_at": datetime(2026, 7, 30, 12, 0, 0),
            "name_clean": "Max Rodriguez",
            "rush_status": None,
        },
    ]
    cur = FakeCursor(script=[rows])
    with patch("backend.management_issues.table_exists", return_value=True), patch(
        "backend.management_issues.table_has_column", return_value=True
    ), patch(
        "backend.rinse_order_instances.ensure_rinse_order_instances_table"
    ):
        # Only first query returns both OIs (exact match)
        out = search_issue_bags(cur, 3, "A347CPMO70", limit=10)
    assert len(out["results"]) == 2
    assert {r["order_instance_id"] for r in out["results"]} == {4951, 4800}
    assert out["results"][0]["bag_id"] == "A347CPMO70"
    assert cur.query_count <= 5


def test_search_org_isolation_params():
    cur = FakeCursor(script=[[]])
    with patch("backend.management_issues.table_exists", return_value=True), patch(
        "backend.management_issues.table_has_column", return_value=False
    ), patch(
        "backend.rinse_order_instances.ensure_rinse_order_instances_table"
    ):
        search_issue_bags(cur, 99, "ABCDEF12", limit=10)
    assert cur.executed
    assert cur.executed[0][1][0] == 99


def test_order_context_mismatch():
    oi = {
        "order_instance_id": 10,
        "bag_id": "OTHERBAG1",
        "service_type": "WF",
        "completed_at": None,
        "completed_by_employee_name": None,
        "source_cycle_id": None,
        "cycle_anchor_at": datetime(2026, 9, 1, 12, 0, 0),
    }
    cur = FakeCursor(script=[oi])
    with patch("backend.rinse_order_instances.ensure_rinse_order_instances_table"), patch(
        "backend.management_issues.table_exists", return_value=True
    ):
        out = build_order_context(cur, 3, bag_id="A347CPMO70", order_instance_id=10)
    assert out["error"] == "bag_id_order_instance_mismatch"


def test_create_rejects_typed_only_selection():
    cur = FakeCursor()
    with patch("backend.management_issues.seed_mgmt_issue_taxonomy"), patch(
        "backend.management_issues._validate_taxonomy", return_value=None
    ):
        out = create_issue(
            cur,
            3,
            {
                "typed_bag_id": "A347CPMO70",
                "bag_id": "A347CPMO70",
                "issue_category": "MISSING",
                "issue_subtype": "MISSING_ITEM",
            },
            actor_user_id=1,
            actor_name="Mgr",
        )
    assert out["error"] == "selection_required"


def test_create_unmatched_requires_fields():
    cur = FakeCursor()
    with patch("backend.management_issues.seed_mgmt_issue_taxonomy"), patch(
        "backend.management_issues._validate_taxonomy", return_value=None
    ):
        out = create_issue(
            cur,
            3,
            {
                "matched_state": UNMATCHED,
                "unmatched": True,
                "issue_category": "OTHER",
                "issue_subtype": "OTHER",
                "manual_identifier": "x",
            },
            actor_user_id=1,
            actor_name="Mgr",
        )
    assert out["error"] == "unmatched_fields_required"


def test_create_matched_happy_path():
    ctx = {
        "bag_id": "A347CPMO70",
        "order_instance_id": 4951,
        "customer_name": "Max",
        "service_type": "WF",
        "rush": False,
        "production_date_et": "2026-09-12",
        "completed_at_et": "2026-09-12 15:44:00",
        "attribution_candidates": [
            {
                "role_key": "folder",
                "stage_key": "folder",
                "employee_name": "Jennifer Farfan",
                "attribution_source": "oi_window_fold_evidence",
                "confidence": "high",
                "is_primary_candidate": True,
            }
        ],
    }
    cur = FakeCursor(
        script=[
            None,  # insert issue
            None,  # insert attr
            None,  # event created
            None,  # event attribution
            # get_issue select
            {
                "id": 1,
                "organization_id": 3,
                "matched_state": MATCHED,
                "bag_id": "A347CPMO70",
                "order_instance_id": 4951,
                "manual_identifier": None,
                "unmatched_reason": None,
                "customer_name_snapshot": "Max",
                "service_type_snapshot": "WF",
                "rush_snapshot": 0,
                "production_date_et": date(2026, 9, 12),
                "completed_at_et": datetime(2026, 9, 12, 15, 44),
                "issue_category": "MISSING",
                "issue_subtype": "MISSING_ITEM",
                "reported_at_et": datetime(2026, 9, 13, 12, 0),
                "description": "test",
                "internal_notes": None,
                "status": "open",
                "severity": None,
                "resolution_type": None,
                "resolution_notes": None,
                "resolved_at_et": None,
                "claim_amount": None,
                "vendor_percentage": None,
                "final_vendor_claim": None,
                "external_issue_id": None,
                "external_issue_url": None,
                "external_type": None,
                "source": "manual",
                "created_by_user_id": 1,
                "created_by_name": "Mgr",
                "updated_by_user_id": 1,
                "updated_by_name": "Mgr",
                "created_at": datetime(2026, 9, 13, 12, 0),
                "updated_at": None,
            },
            [
                {
                    "id": 1,
                    "issue_id": 1,
                    "employee_user_id": None,
                    "employee_name_snapshot": "Jennifer Farfan",
                    "role_key": "folder",
                    "stage_key": "folder",
                    "attribution_source": "oi_window_fold_evidence",
                    "confidence": "high",
                    "is_primary": 1,
                    "is_manager_override": 0,
                    "is_confirmed": 0,
                    "is_not_applicable": 0,
                    "original_employee_name": "Jennifer Farfan",
                    "original_role_key": "folder",
                    "override_reason": None,
                }
            ],
        ]
    )
    cur.lastrowid = 1
    with patch("backend.management_issues.seed_mgmt_issue_taxonomy"), patch(
        "backend.management_issues._validate_taxonomy", return_value=None
    ), patch(
        "backend.management_issues.build_order_context", return_value=ctx
    ), patch(
        "backend.management_issues.ensure_mgmt_issues_tables"
    ):
        out = create_issue(
            cur,
            3,
            {
                "matched_state": MATCHED,
                "selected": True,
                "selection_token": "A347CPMO70:4951",
                "bag_id": "A347CPMO70",
                "order_instance_id": 4951,
                "issue_category": "MISSING",
                "issue_subtype": "MISSING_ITEM",
                "description": "test",
            },
            actor_user_id=1,
            actor_name="Mgr",
        )
    assert "issue" in out
    assert out["issue"]["bag_id"] == "A347CPMO70"
    assert out["attributions"][0]["employee_name_snapshot"] == "Jennifer Farfan"


def test_dashboard_by_issue_math():
    cur = FakeCursor(
        script=[
            # current agg
            [
                {
                    "issue_category": "MISSING",
                    "cnt": 12,
                    "open_cnt": 4,
                    "resolved_cnt": 8,
                    "claim_sum": 100,
                    "final_sum": 50,
                }
            ],
            # prior agg
            [
                {
                    "issue_category": "MISSING",
                    "cnt": 8,
                    "open_cnt": 1,
                    "resolved_cnt": 7,
                    "claim_sum": 40,
                    "final_sum": 20,
                }
            ],
        ]
    )
    with patch("backend.management_issues.ensure_mgmt_issues_tables"), patch(
        "backend.management_issues.business_today", return_value=date(2026, 9, 13)
    ), patch(
        "backend.management_issues._completed_oi_count", side_effect=[286, 250]
    ):
        out = dashboard_by_issue(cur, 3, period="30d", date_basis="production")
    assert out["kpis"]["total_issues"] == 12
    assert out["kpis"]["issue_rate_per_100"] == _rate(12, 286)
    assert out["categories"][0]["count"] == 12
    assert out["categories"][0]["rate_per_100"] == _rate(12, 286)


def test_dashboard_by_employee_rate_unavailable_for_sorter():
    cur = FakeCursor(
        script=[
            [
                {
                    "employee_name": "Alex",
                    "employee_user_id": None,
                    "role_key": "sorter",
                    "issue_count": 3,
                    "claim_exposure": 0,
                    "mix_raw": "MISSING,MISSING,DAMAGE",
                }
            ],
            [],  # prior
        ]
    )
    with patch("backend.management_issues.ensure_mgmt_issues_tables"), patch(
        "backend.management_issues.business_today", return_value=date(2026, 9, 13)
    ), patch(
        "backend.management_issues.table_exists", return_value=False
    ):
        out = dashboard_by_employee(cur, 3, period="30d")
    assert out["employees"][0]["rate_available"] is False
    assert out["employees"][0]["issue_rate_per_100"] is None


def test_hub_roles_constant_excludes_rinse():
    from backend.management_issues_routes import HUB_ROLES

    assert "RINSE" not in HUB_ROLES
    assert "ADMIN" in HUB_ROLES
    assert "MANAGER" in HUB_ROLES


def test_counting_cursor_budget_search():
    inner = FakeCursor(script=[[], [], []])
    counting = CountingCursor(inner)
    with patch("backend.management_issues.table_exists", return_value=True), patch(
        "backend.management_issues.table_has_column", return_value=False
    ), patch(
        "backend.rinse_order_instances.ensure_rinse_order_instances_table"
    ):
        search_issue_bags(counting, 3, "ZZZZNOPE", limit=10)
    assert counting.query_count <= 5
