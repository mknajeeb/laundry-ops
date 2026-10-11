"""Scan Chronology Wash & Fold / Hang Dry checkboxes (Scan Chronology only)."""

from datetime import date, datetime

import pytest

from backend import rinse_operational_day, rinse_scan_chronology
from backend.rinse_operational_day import build_operational_views
from backend.rinse_scan_chronology import build_scan_chronology_payload
from backend.scan_chronology_service_filter import parse_service_types

DAY = date(2026, 10, 9)
REGISTRY = {"WF1": "WF", "WF2": "WF", "HD1": "HD"}  # UNK1 has no registry row
BOTH, WF, HD, NONE = None, frozenset({"WF"}), frozenset({"HD"}), frozenset()


def _at(h, m=0):
    return datetime(2026, 10, 9, h, m)


class RegistryCursor:
    """Answers only the rinse_bag_registry service lookup; any other SQL fails the test."""

    def __init__(self):
        self.statements = []
        self._result = []

    def execute(self, sql, params=()):
        text = " ".join(sql.split())
        self.statements.append(text)
        assert "FROM rinse_bag_registry" in text, f"unexpected SQL: {text}"
        assert text.lstrip().upper().startswith("SELECT")
        bags = params[1:]
        self._result = [
            {"bag_id": b, "service_type": REGISTRY[b]} for b in bags if b in REGISTRY
        ]

    def fetchall(self):
        return list(self._result)

    def close(self):
        pass


def _ev(bag, purpose, ts, user, rack=None):
    return {
        "bag_id": bag,
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "user_name": user,
        "rack": rack,
        "id": 1,
        "scan_index": 1,
    }


def _bag_events(bag, minute, sorter, washer, dryer):
    return [
        _ev(bag, "sent-to-vendor", _at(5), "Portal"),
        _ev(bag, "weight-entry", _at(6, minute), "Francis"),
        _ev(bag, "add-photos", _at(6, minute + 5), sorter),
        _ev(bag, "start-cleaning", _at(7, minute), washer, "W3-30-VW"),
        _ev(bag, "drying", _at(8, minute), dryer, "D2-30-VW"),
    ]


def _views():
    events = [
        *_bag_events("WF1", 0, "Francis", "Maria Perez", "Maria Perez"),
        *_bag_events("WF2", 10, "Francis", "Maria Perez", "Varun"),
        *_bag_events("HD1", 20, "Yesenia", "Maria Perez", "Varun"),
        *_bag_events("UNK1", 30, "Yesenia", "Varun", "Varun"),
    ]
    return build_operational_views(
        events=events, segments=[], name_index={}, selected_date_et=DAY, now=_at(23)
    )


LOCAL_SESSIONS = [
    {"id": 1, "employee": "Francis", "role": "sorting", "start_et": _at(6), "end_et": _at(7)},
    {"id": 2, "employee": "Yesenia", "role": "sorting", "start_et": _at(6, 15), "end_et": _at(6, 30)},
]


@pytest.fixture
def day(monkeypatch):
    monkeypatch.setattr(rinse_operational_day, "load_operational_day", lambda *a, **k: _views())
    monkeypatch.setattr(
        rinse_scan_chronology,
        "list_local_sessions",
        lambda cur, org, d, role=None: [s for s in LOCAL_SESSIONS if s["role"] == role],
    )
    cur = RegistryCursor()

    def payload(stage, service_types, **kw):
        return build_scan_chronology_payload(
            cur, 3, selected_date_et=DAY, stage=stage, service_types=service_types, **kw
        )

    payload.cursor = cur
    return payload


def _bags(p):
    return sorted({r["bag_id"] for r in p["sessions"]})


# --- Parameter parsing -------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        ("WF,HD", None),
        ("hd, wf", None),
        ("WF", frozenset({"WF"})),
        ("hd", frozenset({"HD"})),
        ("Hang Dry", frozenset({"HD"})),
        ("none", frozenset()),
        ("", frozenset()),
    ],
)
def test_parse_service_types(raw, expected):
    assert parse_service_types(raw) == expected


def test_parse_service_types_rejects_unknown():
    with pytest.raises(ValueError):
        parse_service_types("DC")


# --- Operational tabs: rows and summaries -----------------------------------


@pytest.mark.parametrize(
    "service_types, bags",
    [
        (BOTH, ["HD1", "UNK1", "WF1", "WF2"]),
        (WF, ["WF1", "WF2"]),
        (HD, ["HD1"]),
        (NONE, []),
    ],
)
@pytest.mark.parametrize("stage", ["weighing", "sorting", "washing", "drying"])
def test_stage_rows_follow_service_selection(day, stage, service_types, bags):
    p = day(stage, service_types)
    assert _bags(p) == bags
    assert p["service_types"] == [
        s for s in ("WF", "HD") if service_types is None or s in service_types
    ]


@pytest.mark.parametrize(
    "service_types, n", [(BOTH, 4), (WF, 2), (HD, 1), (NONE, 0)]
)
def test_summary_totals_follow_service_selection(day, service_types, n):
    assert day("weighing", service_types)["summary"]["total_bags"] == n
    assert day("weighing", service_types)["summary"]["total_sessions"] == n
    assert day("sorting", service_types)["summary"]["total_bags"] == n
    wash = day("washing", service_types)["summary"]
    assert (wash["washer_loads"], wash["unique_bags_handled"]) == (n, n)
    dry = day("drying", service_types)["summary"]
    assert (dry["dryer_loads"], dry["unique_bags_handled"]) == (n, n)
    assert day("washer_utilization", service_types)["summary"]["total_loads"] == n
    assert day("dryer_utilization", service_types)["summary"]["total_loads"] == n


def test_both_checked_is_unfiltered_and_skips_lookup(day):
    p = day("sorting", BOTH)
    assert len(p["sessions"]) == 4
    assert day.cursor.statements == []


def test_unclassified_bag_only_shown_when_both_checked(day):
    assert "UNK1" in _bags(day("washing", BOTH))
    assert "UNK1" not in _bags(day("washing", WF))
    assert "UNK1" not in _bags(day("washing", HD))


def test_employee_filter_combines_with_service_selection(day):
    assert _bags(day("washing", BOTH, employee_filter="Maria Perez")) == ["HD1", "WF1", "WF2"]
    assert _bags(day("washing", WF, employee_filter="Maria Perez")) == ["WF1", "WF2"]
    assert _bags(day("washing", HD, employee_filter="Maria Perez")) == ["HD1"]
    assert _bags(day("sorting", HD, employee_filter="Francis")) == []
    assert day("drying", WF, employee_filter="Varun")["employees"] == ["Varun"]


# --- Local sessions: productivity respects the selection --------------------


def _local(p):
    s = p["local_sessions"]["summary"]
    per = {x["employee"]: x["scans"] for x in p["local_sessions"]["sessions"]}
    return s, per


def test_local_session_metrics_follow_service_selection(day):
    s, per = _local(day("sorting", BOTH))
    assert (s["total_scans"], s["matched_scans"], s["unassigned_scans"]) == (4, 3, 1)
    assert per == {"Francis": 2, "Yesenia": 1}
    assert (s["total_sessions"], s["total_hours"]) == (2, 1.25)
    assert (s["average_per_session"], s["scans_per_hour"]) == (1.5, 2.4)

    s, per = _local(day("sorting", WF))
    assert (s["total_scans"], s["matched_scans"], s["unassigned_scans"]) == (2, 2, 0)
    assert per == {"Francis": 2, "Yesenia": 0}
    assert (s["average_per_session"], s["scans_per_hour"]) == (1.0, 1.6)

    s, per = _local(day("sorting", HD))
    assert (s["total_scans"], s["matched_scans"], s["unassigned_scans"]) == (1, 1, 0)
    assert per == {"Francis": 0, "Yesenia": 1}
    assert (s["average_per_session"], s["scans_per_hour"]) == (0.5, 0.8)

    s, _ = _local(day("sorting", NONE))
    assert (s["total_scans"], s["matched_scans"]) == (0, 0)
    assert s["scans_per_hour"] == 0


def test_filter_never_writes(day):
    for service_types in (BOTH, WF, HD, NONE):
        for stage in ("weighing", "sorting", "washing", "drying"):
            day(stage, service_types)
    for sql in day.cursor.statements:
        assert sql.upper().startswith("SELECT")
        assert "rinse_bag_registry" in sql


# --- User Activity merges the same filtered stages --------------------------


@pytest.mark.parametrize("service_types, n", [(BOTH, 4), (WF, 2), (HD, 1), (NONE, 0)])
def test_user_activity_follows_service_selection(day, service_types, n):
    p = day("user_activity", service_types, activity_type_filter="washing")
    assert p["summary"]["washer_loads"] == n
    assert p["summary"]["total_activities"] == n


# --- Bag-candidate tabs: Folder, Ready to Fold, Process Flow, Coverage, PPW --


def test_folder_rows_and_summary_follow_service_selection(monkeypatch):
    from backend import rinse_folder_chronology as folder

    monkeypatch.setattr(
        folder, "_load_bag_ids_with_folder_activity_on_day", lambda *a: ["WF1", "HD1", "UNK1"]
    )
    monkeypatch.setattr(folder, "_load_scan_events_for_folder_bags", lambda *a: {})
    monkeypatch.setattr(
        folder,
        "extract_folder_session_for_bag",
        lambda bid, events, selected_date_et: {
            "bag_id": bid,
            "employee": "Angelica",
            "folder_start_et": _at(9),
            "folder_end_et": _at(9, 30),
            "duration_seconds": 1800,
            "status": folder.STATUS_COMPLETE,
            "confidence": "exact",
        },
    )
    monkeypatch.setattr(rinse_scan_chronology, "list_local_sessions", lambda *a, **k: [])
    cur = RegistryCursor()
    for service_types, bags in ((BOTH, ["HD1", "UNK1", "WF1"]), (WF, ["WF1"]), (HD, ["HD1"]), (NONE, [])):
        p = build_scan_chronology_payload(
            cur, 3, selected_date_et=DAY, stage="folder", service_types=service_types
        )
        assert _bags(p) == bags
        assert p["summary"]["total_sessions"] == len(bags)
        assert p["summary"]["total_stage_seconds"] == 1800 * len(bags)
        assert p["local_sessions"]["summary"]["total_scans"] == len(bags)


def test_ready_to_fold_candidates_follow_service_selection(monkeypatch):
    from backend import rinse_ready_to_fold_chronology as rtf

    seen = {}
    monkeypatch.setattr(
        rtf, "_load_scan_events_window", lambda *a: [{"bag_id": b} for b in ("WF1", "HD1", "UNK1")]
    )
    monkeypatch.setattr(
        rtf,
        "extract_drying_rows_from_events",
        lambda events: [{"bag_id": e["bag_id"], "timestamp_et": _at(8)} for e in events],
    )
    monkeypatch.setattr(rtf, "_load_bag_metadata", lambda cur, org, ids: seen.setdefault("ids", sorted(ids)) and {})

    def records(**kw):
        seen["dried"] = sorted({r["bag_id"] for r in kw["drying_rows"]})
        return []

    monkeypatch.setattr(rtf, "build_ready_to_fold_bag_records", records)
    for service_types, bags in ((BOTH, ["HD1", "UNK1", "WF1"]), (WF, ["WF1"]), (HD, ["HD1"]), (NONE, [])):
        seen.clear()
        build_scan_chronology_payload(
            RegistryCursor(), 3, selected_date_et=DAY, stage="ready_to_fold", service_types=service_types
        )
        assert seen["ids"] == bags
        assert seen["dried"] == bags


def test_process_flow_candidates_follow_service_selection(monkeypatch):
    from backend import rinse_process_flow_chronology as pf

    seen = {}
    monkeypatch.setattr(
        pf, "_load_scan_events_window", lambda *a: [{"bag_id": b} for b in ("WF1", "HD1", "UNK1")]
    )
    monkeypatch.setattr(
        pf,
        "extract_washing_rows_from_events",
        lambda events: [{"bag_id": e["bag_id"], "timestamp_et": _at(7)} for e in events],
    )
    monkeypatch.setattr(pf, "extract_drying_rows_from_events", lambda events: [])

    def compose(**kw):
        seen["bags"] = sorted(kw["events_by_bag"])
        return []

    monkeypatch.setattr(pf, "compose_process_flow_rows_for_bags", compose)
    for service_types, bags in ((BOTH, ["HD1", "UNK1", "WF1"]), (WF, ["WF1"]), (HD, ["HD1"]), (NONE, [])):
        build_scan_chronology_payload(
            RegistryCursor(), 3, selected_date_et=DAY, stage="process_flow", service_types=service_types
        )
        assert seen["bags"] == bags


def test_coverage_audit_rows_and_summary_follow_service_selection(monkeypatch):
    from backend import rinse_scan_coverage_audit as cov

    monkeypatch.setattr(
        cov,
        "load_processed_bag_ids_for_day",
        lambda *a: (["WF1", "WF2", "HD1", "UNK1"], {b: ["scan"] for b in ("WF1", "WF2", "HD1", "UNK1")}),
    )
    monkeypatch.setattr(rinse_operational_day, "load_operational_day", lambda *a, **k: _views())
    monkeypatch.setattr(cov, "_load_bag_metadata", lambda cur, org, ids: {})
    monkeypatch.setattr(cov, "_load_completion_timestamps_on_day", lambda *a: {})
    monkeypatch.setattr(cov, "_load_registry_order_ids", lambda *a: {})
    for service_types, bags in (
        (BOTH, ["HD1", "UNK1", "WF1", "WF2"]),
        (WF, ["WF1", "WF2"]),
        (HD, ["HD1"]),
        (NONE, []),
    ):
        p = build_scan_chronology_payload(
            RegistryCursor(), 3, selected_date_et=DAY, stage="coverage_audit", service_types=service_types
        )
        assert sorted(r["bag_id"] for r in p["rows"]) == bags
        assert p["summary"]["total_processed_bags"] == len(bags)


def test_post_processing_weight_candidates_follow_service_selection(monkeypatch):
    from backend import rinse_post_processing_weight_chronology as ppw

    seen = {}
    monkeypatch.setattr(
        ppw,
        "_load_scan_events_on_day",
        lambda *a: [_ev(b, "weight-entry", _at(10), "Francis") for b in ("WF1", "HD1", "UNK1")],
    )

    def full(cur, org, bags):
        seen["bags"] = sorted(bags)
        return []

    monkeypatch.setattr(ppw, "_load_scan_events_for_bags", full)
    for service_types, bags in ((BOTH, ["HD1", "UNK1", "WF1"]), (WF, ["WF1"]), (HD, ["HD1"]), (NONE, [])):
        ppw.build_post_processing_weight_chronology_payload(
            RegistryCursor(), 3, selected_date_et=DAY, service_types=service_types
        )
        assert seen["bags"] == bags


# --- Route -------------------------------------------------------------------


def test_route_parses_service_types(monkeypatch):
    from flask import Flask

    from backend import rinse_shift_analysis_routes as routes

    calls = []

    class _Conn:
        def cursor(self, dictionary=False):
            return RegistryCursor()

        def close(self):
            pass

    monkeypatch.setattr(routes, "get_db", lambda: _Conn())
    monkeypatch.setattr(
        rinse_scan_chronology,
        "build_scan_chronology_payload",
        lambda cur, org, **kw: calls.append(kw["service_types"]) or {"ok": True},
    )
    app = Flask(__name__)
    routes.register_rinse_shift_analysis_routes(
        app,
        require_user=lambda _c: ({"user_id": 1, "roles": ["ADMIN"], "organization_id": 3}, None, None),
        require_admin=lambda _c: (None, None, None),
        user_org_id=lambda _me: 3,
        parse_date_value=lambda v: date.fromisoformat(str(v)[:10]),
    )
    client = app.test_client()
    base = "/rinse/shift-analysis/scan-chronology?date_et=2026-10-09&stage=sorting"
    assert client.get(base).status_code == 200
    assert client.get(base + "&service_types=WF,HD").status_code == 200
    assert client.get(base + "&service_types=WF").status_code == 200
    assert client.get(base + "&service_types=HD").status_code == 200
    assert client.get(base + "&service_types=none").status_code == 200
    assert client.get(base + "&service_types=XX").status_code == 400
    assert calls == [None, None, frozenset({"WF"}), frozenset({"HD"}), frozenset()]
