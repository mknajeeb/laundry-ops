"""Step-1 drawer: page-scoped snapshot reads, no chronology on list."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from backend.rinse_veewash_step1_api import build_drilldown


D1 = date(2026, 7, 22)


def _summary():
    return {
        "selected_date_et": D1.isoformat(),
        "segments": {
            "wf_rush": {
                "bag_ids": {
                    "new_today": [f"BAG{i:02d}" for i in range(40)],
                    "carryover": [],
                    "completed": [],
                    "pending": [],
                    "review_required": [],
                }
            },
            "all": {
                "bag_ids": {
                    "new_today": [f"BAG{i:02d}" for i in range(40)],
                    "review_required": ["BAG00", "BAG01"],
                }
            },
        },
        "review_by_reason": {"WF_BULK_WORKITEM_REVIEW": ["BAG00", "BAG01"]},
        "review_reasons_by_bag": {
            "BAG00": ["WF_BULK_WORKITEM_REVIEW"],
            "BAG01": ["WF_BULK_WORKITEM_REVIEW"],
        },
        "shift_day": {"status": "OPEN"},
    }


def _snap(bid: str) -> dict:
    return {
        "bag_id": bid,
        "service_type": "WF",
        "rush_status": "RUSH",
        "new_or_carryover": "new_today",
        "effective_status": "pending",
        "review_reason_codes": [],
        "bag_snapshot": {
            "bag_id": bid,
            "customer_name": f"Cust {bid}",
            "service_type": "WF",
            "rush_flag": "RUSH",
            "outcome": "pending",
            "entry_class": "new_today",
        },
    }


def test_drilldown_list_loads_only_page_of_bags_not_full_day():
    cursor = MagicMock()
    summary = _summary()
    page_ids = [f"BAG{i:02d}" for i in range(25)]
    with (
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value={"status": "OPEN", "headline": summary}),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=summary),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[_snap(b) for b in page_ids],
        ) as load_page,
        patch("backend.rinse_veewash_shift_day.load_day_bags") as load_all,
        patch("backend.rinse_bulk_workitems.load_bulk_workitem_scan_map", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bulk_resolutions", return_value={}),
        patch("backend.rinse_bulk_workitems.list_workitems", return_value=[]),
    ):
        out = build_drilldown(
            cursor,
            3,
            selected_date_et=D1,
            metric="new_today",
            service="wf",
            rush="rush",
            page=1,
            page_size=25,
            include_details=False,
        )
    load_all.assert_not_called()
    load_page.assert_called_once()
    called_ids = load_page.call_args.args[3]
    assert called_ids == page_ids
    assert len(out["bags"]) == 25
    assert out["pagination"]["total"] == 40
    assert out["pagination"]["has_more"] is True
    for bag in out["bags"]:
        assert bag.get("scans") == []
        assert "chronology" not in bag


def test_drilldown_list_does_not_include_full_chronology():
    cursor = MagicMock()
    summary = _summary()
    with (
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value={"status": "OPEN", "headline": summary}),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=summary),
        patch(
            "backend.rinse_veewash_shift_day.load_day_bags_by_ids",
            return_value=[_snap("BAG00"), _snap("BAG01")],
        ),
        patch("backend.rinse_bulk_workitems.load_bulk_workitem_scan_map", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bag_bulk_lines", return_value={}),
        patch("backend.rinse_bulk_workitems.load_bulk_resolutions", return_value={}),
        patch("backend.rinse_bulk_workitems.list_workitems", return_value=[{"id": 1, "name": "Bath Mat"}]),
        patch("backend.rinse_veewash_step1_api.load_scans_for_bags") as scans,
    ):
        out = build_drilldown(
            cursor,
            3,
            selected_date_et=D1,
            metric="review_required",
            page=1,
            page_size=25,
            include_details=False,
        )
    scans.assert_not_called()
    assert out["bags"][0]["scans"] == []
    assert out["active_bulk_workitems"]


def test_summary_omits_bag_rows_when_requested():
    from backend.rinse_veewash_shift_day import build_or_load_step1_for_date

    cursor = MagicMock()
    day = {
        "status": "OPEN",
        "headline": _summary(),
        "shift_date_et": D1,
    }
    with (
        patch("backend.rinse_veewash_shift_day.get_day_record", return_value=day),
        patch("backend.rinse_veewash_shift_day.summary_from_day_record", return_value=_summary()),
        patch("backend.rinse_veewash_shift_day.day_bag_count", return_value=40),
        patch("backend.rinse_veewash_shift_day.load_day_bags") as load_all,
        patch("backend.rinse_veewash_shift_day.today_et", return_value=date(2026, 7, 23)),
        patch("backend.rinse_veewash_shift_day.get_step1_activation_date", return_value=D1),
    ):
        wl, summary, _meta = build_or_load_step1_for_date(
            cursor, 3, D1, persist_live=False, include_bag_rows=False
        )
    load_all.assert_not_called()
    assert summary["segments"]["wf_rush"]["bag_ids"]["new_today"]
    assert wl.get("bag_rows_omitted") is True
    assert wl.get("rows") == []
