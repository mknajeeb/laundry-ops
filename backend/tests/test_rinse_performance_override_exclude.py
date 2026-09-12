"""Override / exclude / fingerprint stability for Rinse publication."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_performance_approvals import (
    ACTION_EXCLUDE,
    ACTION_INCLUDE,
    ACTION_OVERRIDE,
    approval_status_map,
    exclude_session_publication,
    folder_session_fingerprint,
    include_session_publication,
    list_active_approvals,
    override_published_rate,
    upsert_approved_snapshot,
    weighted_rate_from_rows,
)
from backend.rinse_performance_roles import ROLE_FOLDER


DAY = date(2026, 9, 11)


def _snap(**over):
    base = {
        "business_date_et": DAY,
        "session_id": "WF-1011",
        "segment_id": 1011,
        "employee_user_id": 36,
        "employee_name": "Yessenia (Veewash)",
        "metric_key": "lbs_per_hour",
        "metric_unit": "lb/hr",
        "published_numerator": 329.1,
        "published_denominator": 6.5103,
        "published_metric_value": 50.5507,
        "calculated_numerator": 329.1,
        "calculated_denominator": 6.5103,
        "calculated_metric_value": 50.5507,
        "published_quantity": 329.1,
        "published_duration_hours": 6.5103,
        "published_session_start_et": "2026-09-11 07:00:00",
        "published_session_end_et": "2026-09-11 13:30:00",
        "content_fingerprint": "fp-yess",
    }
    base.update(over)
    return base


def test_fingerprint_ignores_orders_array():
    sess = {
        "session_id": "WF-1011",
        "employee": "Yessenia (Veewash)",
        "total_pre_lbs": 329.1,
        "performance_hours": 6.5103,
        "lbs_per_hour": 50.5507,
        "orders_completed": 14,
        "start_time": "a",
        "end_time": "b",
        "performance_basis": "session_end",
        "role_status": "closed",
    }
    with_orders = {**sess, "orders": [{"bag_id": "AAA"}, {"bag_id": "BBB"}]}
    assert folder_session_fingerprint(sess) == folder_session_fingerprint(with_orders)
    assert folder_session_fingerprint(sess) == folder_session_fingerprint({**sess, "orders": []})


def test_override_preserves_weighted_math():
    # rate 45 with den 6.5103 → num = 45 * 6.5103
    den = 6.5103
    rate = 45.0
    pub_num = round(rate * den, 4)
    rows = [
        {
            "published_numerator": pub_num,
            "published_denominator": den,
            "published_metric_value": rate,
        },
        {
            "published_numerator": 69.2,
            "published_denominator": 2.1947,
            "published_metric_value": 31.5305,
        },
    ]
    weighted = weighted_rate_from_rows(rows)
    assert weighted == pytest.approx((pub_num + 69.2) / (den + 2.1947), rel=1e-4)
    avg_rates = (rate + 31.5305) / 2
    assert abs(weighted - avg_rates) > 1.0


def test_override_and_exclude_roundtrip_sql_shape():
    """Cursor executes expected UPDATE/INSERT shapes (no live DB)."""
    cur = MagicMock()
    # get_approval_row path via SELECT then UPDATE
    cur.fetchone.side_effect = [
        {
            "session_id": "WF-1011",
            "business_date_et": DAY,
            "published_metric_value": 50.5507,
            "published_numerator": 329.1,
            "published_denominator": 6.5103,
            "calculated_denominator": 6.5103,
            "calculated_metric_value": 50.5507,
            "content_fingerprint": "fp",
            "invalidated_at": None,
            "excluded_at": None,
        }
    ]
    cur.fetchall.return_value = []

    with patch(
        "backend.rinse_performance_approvals.ensure_rinse_performance_approval_tables"
    ), patch(
        "backend.rinse_performance_approvals.get_approval_row",
        return_value={
            "session_id": "WF-1011",
            "business_date_et": DAY,
            "published_metric_value": 50.5507,
            "published_numerator": 329.1,
            "published_denominator": 6.5103,
            "calculated_denominator": 6.5103,
            "calculated_metric_value": 50.5507,
            "content_fingerprint": "fp",
            "invalidated_at": None,
            "excluded_at": None,
        },
    ):
        out = override_published_rate(
            cur,
            3,
            role_key=ROLE_FOLDER,
            session_id="WF-1011",
            published_metric_value=45.0,
            reason="acceptance",
            actor_user_id=1,
            actor_name="Admin",
        )
        assert out["ok"] is True
        assert out["action"] == ACTION_OVERRIDE
        assert out["published_metric_value"] == 45.0
        assert out["publication"]["is_rate_override"] is True

        ex = exclude_session_publication(
            cur, 3, role_key=ROLE_FOLDER, session_id="WF-1011", reason="outlier"
        )
        assert ex["ok"] is True
        assert ex["action"] == ACTION_EXCLUDE
        assert ex["publication"]["status"] == "EXCLUDED"

        inc = include_session_publication(
            cur, 3, role_key=ROLE_FOLDER, session_id="WF-1011"
        )
        assert inc["ok"] is True
        assert inc["action"] == ACTION_INCLUDE


def test_approval_status_map_excluded():
    cur = MagicMock()
    cur.fetchall.return_value = [
        {
            "session_id": "WF-1",
            "invalidated_at": None,
            "excluded_at": "2026-09-12",
            "approved_at": "2026-09-12",
            "content_fingerprint": "x",
            "published_metric_value": 40,
            "calculated_metric_value": 50,
            "is_rate_override": 0,
            "override_reason": None,
            "published_numerator": 1,
            "published_denominator": 1,
            "calculated_numerator": 1,
            "calculated_denominator": 1,
        }
    ]
    with patch(
        "backend.rinse_performance_approvals.ensure_rinse_performance_approval_tables"
    ):
        m = approval_status_map(cur, 3, role_key=ROLE_FOLDER, session_ids=["WF-1", "WF-2"])
    assert m["WF-1"]["status"] == "EXCLUDED"
    assert m["WF-2"]["status"] == "UNAPPROVED"


def test_list_active_requires_not_excluded():
    cur = MagicMock()
    cur.fetchall.return_value = []
    with patch(
        "backend.rinse_performance_approvals.ensure_rinse_performance_approval_tables"
    ):
        list_active_approvals(cur, 3, role_key=ROLE_FOLDER, week_start=DAY, week_end=DAY)
    sql = cur.execute.call_args[0][0]
    assert "invalidated_at IS NULL" in sql
    assert "excluded_at IS NULL" in sql


def test_approve_uses_session_card_without_day_rebuild():
    from backend.rinse_performance_folder_publisher import approve_folder_session

    sess = {
        "session_id": "WF-1011",
        "segment_id": 1011,
        "user_id": 36,
        "employee": "Yessenia (Veewash)",
        "total_pre_lbs": 329.1,
        "performance_hours": 6.5103,
        "lbs_per_hour": 50.5507,
        "orders_completed": 14,
        "start_time": "2026-09-11 07:00:00",
        "end_time": "2026-09-11 13:30:00",
        "performance_basis": "session_end",
        "role_status": "closed",
    }
    cur = MagicMock()
    with (
        patch(
            "backend.rinse_performance_folder_publisher.build_day_folder_performance"
        ) as build_day,
        patch(
            "backend.rinse_performance_folder_publisher.upsert_approved_snapshot",
            return_value={
                "ok": True,
                "publication": {"status": "APPROVED"},
                "published_metric_value": 50.5507,
            },
        ) as upsert,
    ):
        out = approve_folder_session(
            cur,
            3,
            selected_date_et=DAY,
            session_id="WF-1011",
            session=sess,
            actor_user_id=1,
        )
    build_day.assert_not_called()
    assert upsert.called
    assert out["ok"] is True
    assert out["status"] == "approved"


def test_schema_ensure_skips_after_warm():
    import backend.rinse_performance_approvals as mod

    mod._SCHEMA_READY = False
    cur = MagicMock()
    with patch("backend.rinse_performance_approvals.table_exists", return_value=True):
        with patch.object(mod, "_ensure_publication_extension_columns") as ext:
            mod.ensure_rinse_performance_approval_tables(cur)
            mod.ensure_rinse_performance_approval_tables(cur)
            assert ext.call_count == 1
    assert mod._SCHEMA_READY is True
    # third call after warm must no-op entirely
    cur.reset_mock()
    mod.ensure_rinse_performance_approval_tables(cur)
    assert cur.execute.call_count == 0
