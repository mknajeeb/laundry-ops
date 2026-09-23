"""Scan Chronology summary KPIs must match the active employee filter."""

from datetime import datetime, timedelta

from backend.rinse_operational_day import chronology_payload_from_views


def _perf(employee, user_id, *, sort_hours=0.0, sorting_bags=0, washer_loads=0, dryer_loads=0):
    return {
        "user_id": user_id,
        "employee": employee,
        "sorting_bags": sorting_bags,
        "sort_hours": sort_hours,
        "sorting_bags_per_hour": (
            round(sorting_bags / sort_hours, 2) if sort_hours > 0 else None
        ),
        "washer_loads": washer_loads,
        "dryer_loads": dryer_loads,
        "unique_bags_handled": washer_loads or dryer_loads,
        "operator_hours": 0.0,
        "weighing_bags": 0,
    }


def _sort_row(bag_id, employee, user_id, ts):
    return {
        "bag_id": bag_id,
        "employee": employee,
        "user_id": user_id,
        "sort_time_et": ts,
        "time_et": ts,
    }


def _wash(bag_id, employee, user_id, ts, rack="W1-30-VW"):
    return {
        "bag_id": bag_id,
        "employee": employee,
        "user_id": user_id,
        "timestamp_et": ts,
        "washer_rack": rack,
    }


def _dry(bag_id, employee, user_id, ts, rack="D1-30-VW"):
    return {
        "bag_id": bag_id,
        "employee": employee,
        "user_id": user_id,
        "timestamp_et": ts,
        "dryer_rack": rack,
    }


def _sep23_views():
    """Synthetic Sep 23 contract matching production acceptance figures."""
    base = datetime(2026, 9, 23, 5, 33)
    francis_sort = [
        _sort_row(f"F{i:03d}", "Francis", 16, base + timedelta(minutes=i))
        for i in range(132)
    ]
    maria_sort = [
        _sort_row(
            f"M{i:03d}",
            "Maria Perez",
            31,
            datetime(2026, 9, 23, 5, 46) + timedelta(minutes=i),
        )
        for i in range(10)
    ]
    varun_washes = [
        _wash(
            f"VW{i:03d}",
            "Varun Kumar Mongia",
            26,
            datetime(2026, 9, 23, 6, 3) + timedelta(minutes=i),
            f"W{i % 30}-60-VW",
        )
        for i in range(124)
    ]
    varun_dries = [
        _dry(
            f"VW{i:03d}",
            "Varun Kumar Mongia",
            26,
            datetime(2026, 9, 23, 7, 9) + timedelta(minutes=i),
            f"D{i % 30}-30-VW",
        )
        for i in range(78)
    ]
    # Maria dries bags that Varun already washed so All unique bags stays 124.
    maria_dries = [
        _dry(
            f"VW{i:03d}",
            "Maria Perez",
            31,
            datetime(2026, 9, 23, 7, 9) + timedelta(minutes=i),
            f"D{i % 20}-50-VW",
        )
        for i in range(29)
    ]
    wash_dry = []
    for w in varun_washes:
        dryer = next((d for d in maria_dries if d["bag_id"] == w["bag_id"]), None)
        wash_dry.append(
            {
                "wash_dry_row": True,
                "bag_id": w["bag_id"],
                "employee": w["employee"],
                "washer_employee": w["employee"],
                "dryer_employee": dryer["employee"] if dryer else None,
                "washer_rack": w["washer_rack"],
                "dryer_rack": dryer["dryer_rack"] if dryer else None,
                "wash_time_et": w["timestamp_et"],
                "dry_time_et": dryer["timestamp_et"] if dryer else None,
            }
        )
    for d in varun_dries:
        if any(r["bag_id"] == d["bag_id"] and r.get("dry_time_et") for r in wash_dry):
            continue
        wash_dry.append(
            {
                "wash_dry_row": True,
                "bag_id": d["bag_id"],
                "employee": d["employee"],
                "washer_employee": None,
                "dryer_employee": d["employee"],
                "dryer_rack": d["dryer_rack"],
                "wash_time_et": None,
                "dry_time_et": d["timestamp_et"],
            }
        )
    return {
        "date_et": "2026-09-23",
        "sorting": francis_sort + maria_sort,
        "washer_loads": varun_washes,
        "dryer_loads": varun_dries + maria_dries,
        "wash_dry": wash_dry,
        "performance": [
            _perf("Francis", 16, sort_hours=8.4181, sorting_bags=132),
            _perf(
                "Maria Perez",
                31,
                sort_hours=1.5425,
                sorting_bags=10,
                dryer_loads=29,
            ),
            _perf(
                "Varun Kumar Mongia",
                26,
                washer_loads=124,
                dryer_loads=78,
            ),
            _perf("VeeWash Test", 23),
        ],
    }


def _sep18_views():
    francis = [
        _sort_row(f"F{i:03d}", "Francis", 16, datetime(2026, 9, 18, 6, 40))
        for i in range(114)
    ]
    yesenia = [
        _sort_row(f"Y{i:03d}", "Yesenia", 36, datetime(2026, 9, 18, 8, 0))
        for i in range(21)
    ]
    return {
        "date_et": "2026-09-18",
        "sorting": francis + yesenia,
        "washer_loads": [],
        "dryer_loads": [],
        "wash_dry": [],
        "performance": [
            _perf("Francis", 16, sort_hours=7.6803, sorting_bags=114),
            _perf("Mithila", 35, sort_hours=0.0017, sorting_bags=0),
            _perf("Yesenia", 36, sort_hours=1.6811, sorting_bags=21),
        ],
    }


def test_sorting_sep23_all_employees_uses_org_sort_hours():
    payload = chronology_payload_from_views(_sep23_views(), "sorting")
    summary = payload["summary"]
    assert summary["total_bags"] == 142
    assert summary["sort_hours"] == 9.9606
    assert summary["sorting_bags_per_hour"] == 14.26


def test_sorting_sep23_francis_uses_employee_sort_hours():
    payload = chronology_payload_from_views(
        _sep23_views(), "sorting", employee_filter="Francis"
    )
    summary = payload["summary"]
    assert summary["total_bags"] == 132
    assert summary["sort_hours"] == 8.4181
    assert summary["sorting_bags_per_hour"] == 15.68
    assert {r["employee"] for r in payload["sessions"]} == {"Francis"}


def test_sorting_sep23_maria_uses_employee_sort_hours():
    payload = chronology_payload_from_views(
        _sep23_views(), "sorting", employee_filter="Maria Perez"
    )
    summary = payload["summary"]
    assert summary["total_bags"] == 10
    assert summary["sort_hours"] == 1.5425
    assert summary["sorting_bags_per_hour"] == 6.48
    assert {r["employee"] for r in payload["sessions"]} == {"Maria Perez"}


def test_sorting_employee_filter_changes_numerator_and_denominator():
    views = _sep23_views()
    all_s = chronology_payload_from_views(views, "sorting")["summary"]
    francis = chronology_payload_from_views(
        views, "sorting", employee_filter="Francis"
    )["summary"]
    maria = chronology_payload_from_views(
        views, "sorting", employee_filter="Maria Perez"
    )["summary"]

    assert all_s["total_bags"] != francis["total_bags"] != maria["total_bags"]
    assert all_s["sort_hours"] != francis["sort_hours"]
    assert francis["sort_hours"] != maria["sort_hours"]
    assert all_s["sorting_bags_per_hour"] != francis["sorting_bags_per_hour"]
    assert francis["sorting_bags_per_hour"] != maria["sorting_bags_per_hour"]
    # Never reuse org hours under an employee filter.
    assert francis["sort_hours"] != all_s["sort_hours"]
    assert maria["sort_hours"] != all_s["sort_hours"]


def test_sorting_sep18_prior_date_regression():
    views = _sep18_views()
    all_s = chronology_payload_from_views(views, "sorting")["summary"]
    assert all_s["total_bags"] == 135
    assert all_s["sort_hours"] == 9.3631
    assert all_s["sorting_bags_per_hour"] == 14.42

    francis = chronology_payload_from_views(
        views, "sorting", employee_filter="Francis"
    )["summary"]
    assert francis["total_bags"] == 114
    assert francis["sort_hours"] == 7.6803
    assert francis["sorting_bags_per_hour"] == 14.84

    yesenia = chronology_payload_from_views(
        views, "sorting", employee_filter="Yesenia"
    )["summary"]
    assert yesenia["total_bags"] == 21
    assert yesenia["sort_hours"] == 1.6811
    assert yesenia["sorting_bags_per_hour"] == 12.49


def test_wash_dry_all_employees_keeps_full_day_totals():
    for stage in ("washing", "drying"):
        summary = chronology_payload_from_views(_sep23_views(), stage)["summary"]
        assert summary["washer_loads"] == 124
        assert summary["dryer_loads"] == 107
        assert summary["unique_bags_handled"] == 124
        assert summary["total_washer_loads"] == 124
        assert summary["total_drying_scans"] == 107


def test_wash_dry_employee_filter_uses_filtered_load_population():
    views = _sep23_views()
    maria_wash = chronology_payload_from_views(
        views, "washing", employee_filter="Maria Perez"
    )
    maria_dry = chronology_payload_from_views(
        views, "drying", employee_filter="Maria Perez"
    )
    for payload in (maria_wash, maria_dry):
        summary = payload["summary"]
        assert summary["washer_loads"] == 0
        assert summary["dryer_loads"] == 29
        assert summary["unique_bags_handled"] == 29
        assert len(payload["washer_loads"]) == 0
        assert len(payload["dryer_loads"]) == 29

    varun = chronology_payload_from_views(
        views, "washing", employee_filter="Varun Kumar Mongia"
    )["summary"]
    assert varun["washer_loads"] == 124
    assert varun["dryer_loads"] == 78
    assert varun["unique_bags_handled"] == 124

    francis = chronology_payload_from_views(
        views, "washing", employee_filter="Francis"
    )["summary"]
    assert francis["washer_loads"] == 0
    assert francis["dryer_loads"] == 0
    assert francis["unique_bags_handled"] == 0


def test_washer_utilization_remains_employee_filtered():
    views = _sep23_views()
    all_u = chronology_payload_from_views(views, "washer_utilization")["summary"]
    assert all_u["total_loads"] == 124
    maria = chronology_payload_from_views(
        views, "washer_utilization", employee_filter="Maria Perez"
    )["summary"]
    assert maria["total_loads"] == 0
    varun = chronology_payload_from_views(
        views, "washer_utilization", employee_filter="Varun Kumar Mongia"
    )["summary"]
    assert varun["total_loads"] == 124
