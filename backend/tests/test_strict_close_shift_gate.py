"""Strict Close Shift gate — no override; unresolved admitted work blocks close."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_veewash_shift_day import (
    CLOSE_NOT_READY_ERROR,
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_READY_TO_CLOSE,
    close_shift_day,
    compute_close_blocking_counts,
    persist_day_snapshot,
    validate_close,
)

D1 = date(2026, 7, 25)
ORG = 3


def _summary(
    *,
    wf_pending=0,
    wf_review=0,
    hd_review=0,
    hd_pending=0,
    completed=70,
    excluded=0,
    active=None,
):
    review = wf_review + hd_review
    pending = wf_pending + hd_pending
    active = completed + pending + review + excluded if active is None else active
    return {
        "active_workload": active,
        "completed": completed,
        "pending": pending,
        "exceptions": {"review_required": review},
        "segments": {
            "all": {
                "active_workload": active,
                "completed": completed,
                "pending": pending,
                "excluded": excluded,
                "exceptions": {"review_required": review},
                "bag_ids": {
                    "completed": [f"C{i}" for i in range(completed)],
                    "pending": [f"P{i}" for i in range(pending)],
                    "review_required": [f"R{i}" for i in range(review)],
                    "excluded": [f"X{i}" for i in range(excluded)],
                },
            },
            "wf": {
                "new_today": completed + wf_pending + wf_review,
                "completed": completed,
                "pending": wf_pending,
                "exceptions": {"review_required": wf_review},
                "bag_ids": {
                    "completed": [f"C{i}" for i in range(completed)],
                    "pending": [f"WP{i}" for i in range(wf_pending)],
                    "review_required": [f"WR{i}" for i in range(wf_review)],
                },
            },
            "hd": {
                "new_today": hd_review + hd_pending,
                "completed": 0,
                "pending": hd_pending,
                "exceptions": {"review_required": hd_review},
                "bag_ids": {
                    "new_today": [f"HD{i}" for i in range(hd_review + hd_pending)],
                    "completed": [],
                    "pending": [f"HP{i}" for i in range(hd_pending)],
                    "review_required": [f"HR{i}" for i in range(hd_review)],
                },
            },
        },
    }


def _bid(prefix: str, i: int) -> str:
    """10-char bag ids (normalize_bag_id rejects short synthetic ids)."""
    return f"{prefix}{i:06d}"[:10]


def _bags_from(*, wf_pending=0, wf_review=0, hd_review=0, hd_partial_ids=None, completed=3, excluded=0):
    rows = []
    for i in range(completed):
        rows.append(
            {
                "bag_id": _bid("DONE", i),
                "service_type": "WF",
                "effective_status": "completed",
            }
        )
    for i in range(excluded):
        rows.append(
            {
                "bag_id": _bid("EXCL", i),
                "service_type": "WF",
                "effective_status": "excluded",
                "disposition": "EXCLUDE",
            }
        )
    for i in range(wf_pending):
        rows.append(
            {
                "bag_id": _bid("WPND", i),
                "service_type": "WF",
                "effective_status": "pending",
            }
        )
    for i in range(wf_review):
        rows.append(
            {
                "bag_id": _bid("WREV", i),
                "service_type": "WF",
                "effective_status": "review_required",
                "review_reason_codes": ["DISAPPEARED_WITHOUT_COMPLETION"],
            }
        )
    for i in range(hd_review):
        rows.append(
            {
                "bag_id": _bid("HREV", i),
                "service_type": "HD",
                "effective_status": "review_required",
            }
        )
    for bid in hd_partial_ids or []:
        # Ensure partial bags are present as HD review members.
        if not any(r["bag_id"] == bid for r in rows):
            rows.append(
                {
                    "bag_id": bid,
                    "service_type": "HD",
                    "effective_status": "review_required",
                }
            )
    return rows


def test_wf_pending_blocks_close():
    bags = _bags_from(wf_pending=2, completed=5)
    v = validate_close(_summary(wf_pending=2, completed=5), day_bags=bags)
    assert v["ok"] is False
    assert v["error"] == CLOSE_NOT_READY_ERROR
    assert v["blocking_counts"]["wf_pending"] == 2


def test_wf_review_required_blocks_close():
    bags = _bags_from(wf_review=1, completed=5)
    v = validate_close(_summary(wf_review=1, completed=5), day_bags=bags)
    assert v["ok"] is False
    assert v["blocking_counts"]["wf_review_required"] == 1


def test_hd_review_required_blocks_close():
    bags = _bags_from(hd_review=2, completed=5)
    v = validate_close(_summary(hd_review=2, completed=5), day_bags=bags)
    assert v["ok"] is False
    assert v["blocking_counts"]["hd_review_required"] == 2


def test_hd_partial_review_blocks_close():
    partial_ids = [_bid("HREV", 0), _bid("HREV", 1)]
    bags = _bags_from(hd_review=2, completed=5, hd_partial_ids=partial_ids)
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"bag_id": partial_ids[0]}, {"bag_id": partial_ids[1]}]
    with patch(
        "backend.daily_operations_hd.ensure_hd_production_tables"
    ), patch("backend.ta_helpers.table_exists", return_value=True):
        v = validate_close(
            _summary(hd_review=2, completed=5),
            cursor=cursor,
            organization_id=ORG,
            shift_date_et=D1,
            day_bags=bags,
        )
    assert v["ok"] is False
    assert v["blocking_counts"]["hd_partially_recorded"] == 2
    assert v["blocking_counts"]["hd_review_required"] == 0


def test_unresolved_exception_blocks_close():
    bags = _bags_from(wf_review=1, completed=4)
    bags.append(
        {
            "bag_id": "ZZORPHAN01",
            "service_type": "WF",
            "effective_status": "disappeared_exception",
        }
    )
    v = validate_close(_summary(wf_review=1, completed=4), day_bags=bags)
    assert v["ok"] is False
    assert v["blocking_counts"]["other_unresolved"] >= 1


def test_excluded_orders_do_not_block_close():
    bags = _bags_from(completed=5, excluded=3)
    v = validate_close(_summary(completed=5, excluded=3), day_bags=bags)
    assert v["ok"] is True
    assert v["blocking_counts"]["wf_pending"] == 0
    assert v["totals"]["approved_excluded"] == 3


def test_all_completed_close_succeeds_and_freezes():
    bags = _bags_from(completed=8, excluded=1)
    summary = _summary(completed=8, excluded=1)
    day = {"status": STATUS_READY_TO_CLOSE, "headline": summary}
    closed = {**day, "status": STATUS_CLOSED}
    cursor = MagicMock()
    with (
        patch("backend.rinse_veewash_shift_day.get_day_record", side_effect=[day, closed]),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=summary),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day.persist_day_snapshot") as persist,
        patch("backend.rinse_veewash_shift_day._write_audit") as audit,
        patch("backend.rinse_employee_completed_bags.clear_step1_productivity_cache"),
        patch(
            "backend.rinse_veewash_shift_day._count_hd_partially_recorded",
            return_value=0,
        ),
    ):
        out = close_shift_day(
            cursor,
            ORG,
            D1,
            actor_user_id=1,
            actor_display_name="Admin",
        )
    assert out["ok"] is True
    persist.assert_not_called()
    audit.assert_called_once()
    assert audit.call_args.kwargs.get("action") == "CLOSE"
    sql = cursor.execute.call_args[0][0]
    assert "UPDATE rinse_shift_monitor_days" in sql
    assert "close_override=%s" in sql
    # close_override forced to 0
    assert cursor.execute.call_args[0][1][5] == 0


def test_failed_close_leaves_no_status_or_audit_mutation():
    bags = _bags_from(wf_pending=1, completed=5)
    summary = _summary(wf_pending=1, completed=5)
    day = {"status": STATUS_OPEN, "headline": summary}
    cursor = MagicMock()
    with (
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value=day),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=summary),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day._write_audit") as audit,
        patch("backend.rinse_veewash_shift_day.persist_day_snapshot") as persist,
        patch(
            "backend.rinse_veewash_shift_day._count_hd_partially_recorded",
            return_value=0,
        ),
    ):
        out = close_shift_day(
            cursor,
            ORG,
            D1,
            actor_user_id=1,
            actor_display_name="Admin",
            allow_unresolved_reviews=True,  # ignored
            reason="please override",
        )
    assert out["ok"] is False
    assert out["error"] == CLOSE_NOT_READY_ERROR
    assert out["blocking_counts"]["wf_pending"] == 1
    audit.assert_not_called()
    persist.assert_not_called()
    cursor.execute.assert_not_called()


def test_override_flag_ignored_when_reviews_remain():
    bags = _bags_from(wf_review=2, completed=5)
    summary = _summary(wf_review=2, completed=5)
    v = validate_close(summary, allow_unresolved_reviews=True, day_bags=bags)
    assert v["ok"] is False
    assert v["checklist"]["override_close_allowed"] is False


def test_productivity_and_workload_kpis_unchanged_across_close():
    bags = _bags_from(completed=6, excluded=1)
    summary = _summary(completed=6, excluded=1)
    day_open = {"status": STATUS_READY_TO_CLOSE, "headline": summary}
    day_closed = {"status": STATUS_CLOSED, "headline": summary}
    before_fp = {
        "employees": [{"employee": "Maria", "completed_bags": 6, "total_credited_lbs": 60.0}],
        "reconciliation": {"credited_total": 6},
        "completed_today_kpi": 6,
        "workload_completed_kpi": 6,
        "active_workload": 7,
    }
    after_fp = deepcopy(before_fp)
    cursor = MagicMock()
    with (
        patch("backend.rinse_veewash_shift_day.get_day_record", side_effect=[day_open, day_closed]),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=summary),
        patch("backend.rinse_veewash_shift_day.load_day_bags", return_value=bags),
        patch("backend.rinse_veewash_shift_day._write_audit"),
        patch("backend.rinse_veewash_shift_day.persist_day_snapshot"),
        patch("backend.rinse_employee_completed_bags.clear_step1_productivity_cache"),
        patch(
            "backend.rinse_veewash_shift_day._count_hd_partially_recorded",
            return_value=0,
        ),
        patch(
            "backend.rinse_employee_completed_bags.build_employee_productivity_dashboard_payload",
            side_effect=[before_fp, after_fp],
        ),
    ):
        from backend.rinse_employee_completed_bags import (
            build_employee_productivity_dashboard_payload,
        )

        before = build_employee_productivity_dashboard_payload(cursor, ORG, selected_date_et=D1)
        out = close_shift_day(
            cursor, ORG, D1, actor_user_id=1, actor_display_name="Admin"
        )
        after = build_employee_productivity_dashboard_payload(cursor, ORG, selected_date_et=D1)
    assert out["ok"] is True
    assert before == after
    assert before["active_workload"] == after["active_workload"]
    assert before["completed_today_kpi"] == after["completed_today_kpi"]


def test_closed_snapshot_immutable_after_later_scrape_persist():
    cursor = MagicMock()
    closed = {"status": STATUS_CLOSED, "headline": _summary(completed=10)}
    with (
        patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"),
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value=closed),
    ):
        out = persist_day_snapshot(
            cursor,
            ORG,
            D1,
            workload={"rows": [{"bag_id": "NEWER"}]},
            summary=_summary(completed=999),
            force=False,
        )
    assert out["status"] == STATUS_CLOSED
    cursor.execute.assert_not_called()


def test_blocking_counts_shape():
    gate = compute_close_blocking_counts(
        _summary(wf_pending=1, wf_review=2, hd_review=3, completed=10),
        day_bags=_bags_from(wf_pending=1, wf_review=2, hd_review=3, completed=10),
    )
    assert set(gate["blocking_counts"]) == {
        "wf_pending",
        "wf_review_required",
        "hd_review_required",
        "hd_partially_recorded",
        "hd_pending_members",
        "other_unresolved",
    }
    assert gate["blocking_counts"]["wf_pending"] == 1
    assert gate["blocking_counts"]["wf_review_required"] == 2
    assert gate["blocking_counts"]["hd_review_required"] == 3
