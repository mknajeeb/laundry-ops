"""Tests for org-scoped Saved Simulations CRUD (mgmt_sim_v1)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from backend.shift_capacity_saved_simulations import (
    PAYLOAD_VERSION,
    TABLE,
    create_saved_simulation,
    delete_saved_simulation,
    get_saved_simulation,
    list_saved_simulations,
    normalize_scenario_payload,
    rename_saved_simulation,
    update_saved_simulation,
)


def _base_payload(**overrides):
    payload = {
        "payload_version": PAYLOAD_VERSION,
        "bag_count": 100,
        "start_time": "9:00 AM",
        "target_time": "4:00 PM",
        "planning_block_size_min": 60,
        "washer_count": 4,
        "dryer_count": 4,
        "weigh_sec_per_bag": 45,
        "sort_min_per_bag": 5,
        "load_washer_min": 3,
        "wash_cycle_min": 30,
        "load_dryer_min": 3,
        "dry_cycle_min": 45,
        "fold_min_per_bag": 6,
        "avg_lbs_per_bag": 20,
        "two_washer_split_pct": 80,
        "two_dryer_split_pct": 80,
        "batch_size": 8,
        "staffing_intervals": [
            {
                "role": "sorter",
                "people": 2,
                "start": "9:00 AM",
                "end": "4:00 PM",
                "mode": "base",
            }
        ],
        "hybrid_intervals": [
            {
                "roles": ["weigher", "washer", "dryer"],
                "people": 1,
                "start": "9:00 AM",
                "end": "4:00 PM",
                "mode": "base",
            }
        ],
    }
    payload.update(overrides)
    return payload


class _FakeCursor:
    def __init__(self):
        self.rows: dict[int, dict] = {}
        self._seq = 0
        self.lastrowid = 0
        self.rowcount = 0
        self._last = []
        self.ensured = False

    def execute(self, sql, params=None):
        sql_n = " ".join(sql.split()).lower()
        params = params or ()
        if sql_n.startswith("create table"):
            self.ensured = True
            return
        if "insert into" in sql_n and TABLE in sql:
            self._seq += 1
            self.lastrowid = self._seq
            org, name, payload, version, created_by, updated_by, last_run_at, last_run = params
            self.rows[self._seq] = {
                "id": self._seq,
                "organization_id": org,
                "name": name,
                "scenario_payload": payload,
                "payload_version": version,
                "created_by_user_id": created_by,
                "updated_by_user_id": updated_by,
                "created_at": "2026-08-13 12:00:00",
                "updated_at": "2026-08-13 12:00:00",
                "last_run_at": last_run_at,
                "last_run_summary": last_run,
            }
            self.rowcount = 1
            return
        if sql_n.startswith("update") and TABLE in sql:
            name, payload, version, updated_by, last_run_at, last_run, org, sid = params
            row = self.rows.get(int(sid))
            if not row or int(row["organization_id"]) != int(org):
                self.rowcount = 0
                return
            row.update(
                {
                    "name": name,
                    "scenario_payload": payload,
                    "payload_version": version,
                    "updated_by_user_id": updated_by,
                    "last_run_at": last_run_at,
                    "last_run_summary": last_run,
                    "updated_at": "2026-08-13 13:00:00",
                }
            )
            self.rowcount = 1
            return
        if sql_n.startswith("delete from") and TABLE in sql:
            org, sid = params
            row = self.rows.get(int(sid))
            if row and int(row["organization_id"]) == int(org):
                del self.rows[int(sid)]
                self.rowcount = 1
            else:
                self.rowcount = 0
            return
        if "from" in sql_n and TABLE in sql and "where organization_id=%s and id=%s" in sql_n:
            org, sid = params
            row = self.rows.get(int(sid))
            if row and int(row["organization_id"]) == int(org):
                self._last = [dict(row)]
            else:
                self._last = []
            return
        if "from" in sql_n and TABLE in sql and "where organization_id=%s" in sql_n:
            org = params[0]
            matched = [dict(r) for r in self.rows.values() if int(r["organization_id"]) == int(org)]
            matched.sort(key=lambda r: (-int(r["id"]),))
            # Strip payload for list queries
            if "scenario_payload" not in sql_n:
                for r in matched:
                    r.pop("scenario_payload", None)
            self._last = matched
            return
        if "last_insert_id" in sql_n:
            self._last = [{"id": self.lastrowid}]
            return

    def fetchone(self):
        rows = getattr(self, "_last", [])
        return rows[0] if rows else None

    def fetchall(self):
        return list(getattr(self, "_last", []) or [])


@pytest.fixture
def cursor():
    return _FakeCursor()


def test_normalize_preserves_custom_hybrid_roles():
    out = normalize_scenario_payload(
        _base_payload(
            hybrid_intervals=[
                {
                    "roles": ["sorter", "folder"],
                    "people": 2,
                    "start": "10:00 AM",
                    "end": "2:00 PM",
                    "mode": "additional",
                }
            ]
        )
    )
    assert out["payload_version"] == PAYLOAD_VERSION
    assert out["hybrid_intervals"][0]["roles"] == ["sorter", "folder"]
    assert out["hybrid_intervals"][0]["people"] == 2
    assert out["hybrid_intervals"][0]["mode"] == "additional"
    assert "block_positions" not in out
    assert "management_outcome" not in out


def test_normalize_legacy_hybrid_string():
    out = normalize_scenario_payload(
        _base_payload(
            hybrid_intervals=[
                {
                    "hybrid": "wash_dry",
                    "people": 1,
                    "start": "9:00 AM",
                    "end": "12:00 PM",
                    "mode": "base",
                }
            ]
        )
    )
    assert out["hybrid_intervals"][0]["roles"] == ["washer", "dryer"]


def test_crud_org_isolation(cursor):
    with patch("backend.shift_capacity_saved_simulations.table_exists", return_value=False):
        a = create_saved_simulation(
            cursor,
            3,
            name="Monday 100 Bags",
            scenario_payload=_base_payload(),
            user_id=11,
            last_run_summary={
                "completed_by_target": 100,
                "target_bags": 100,
                "projected_finish": "2:35 PM",
                "productive_hours": 18.4,
                "status_label": "TARGET MET",
            },
        )
        create_saved_simulation(
            cursor,
            9,
            name="Other Org Sim",
            scenario_payload=_base_payload(bag_count=40),
            user_id=99,
        )
    assert a["id"] == 1
    assert a["scenario_payload"]["hybrid_intervals"][0]["roles"] == [
        "weigher",
        "washer",
        "dryer",
    ]
    assert a["last_run_summary"]["projected_finish"] == "2:35 PM"

    with patch("backend.shift_capacity_saved_simulations.table_exists", return_value=True):
        listed = list_saved_simulations(cursor, 3)
        assert len(listed) == 1
        assert listed[0]["name"] == "Monday 100 Bags"
        assert "scenario_payload" not in listed[0]
        assert get_saved_simulation(cursor, 9, a["id"]) is None
        assert get_saved_simulation(cursor, 3, a["id"])["name"] == "Monday 100 Bags"

        updated = update_saved_simulation(
            cursor,
            3,
            a["id"],
            scenario_payload=_base_payload(bag_count=110),
            last_run_summary={"completed_by_target": 110, "target_bags": 110},
            user_id=11,
        )
        assert updated["scenario_payload"]["bag_count"] == 110

        renamed = rename_saved_simulation(cursor, 3, a["id"], name="Heavy Day", user_id=11)
        assert renamed["name"] == "Heavy Day"

        assert delete_saved_simulation(cursor, 9, a["id"]) is False
        assert delete_saved_simulation(cursor, 3, a["id"]) is True
        assert get_saved_simulation(cursor, 3, a["id"]) is None


def test_fill_rest_normalized_staffing_persisted(cursor):
    """Save stores resulting intervals, not a Fill-rest click flag."""
    payload = _base_payload(
        staffing_intervals=[
            {
                "id": "base-sorter-1",
                "role": "sorter",
                "people": 2,
                "start": "9:00 AM",
                "end": "4:00 PM",
                "mode": "base",
            },
            {
                "id": "temp-sorter-1",
                "role": "sorter",
                "people": 1,
                "start": "11:00 AM",
                "end": "1:00 PM",
                "mode": "additional",
            },
        ]
    )
    with patch("backend.shift_capacity_saved_simulations.table_exists", return_value=False):
        created = create_saved_simulation(
            cursor, 3, name="Fill Rest Result", scenario_payload=payload
        )
    intervals = created["scenario_payload"]["staffing_intervals"]
    assert len(intervals) == 2
    assert intervals[0]["end"] == "4:00 PM"
    assert intervals[1]["mode"] == "additional"
    raw = json.loads(cursor.rows[1]["scenario_payload"])
    assert "fill_rest" not in raw


def test_rejects_unknown_payload_version():
    with pytest.raises(ValueError, match="payload_version"):
        normalize_scenario_payload(_base_payload(payload_version="mgmt_sim_v0"))
