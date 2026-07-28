"""Permanent Jul 27 org3 WF completion parity lock (Release A).

Runs against a live DB when ``RUN_JUL27_COMPLETION_PARITY=1``.
Otherwise validates the fixture contract shape so CI still guards the dataset.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "shift_monitor_jul27_org3_wf_completion_parity.json"
)


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def test_jul27_parity_fixture_contract():
    data = _load()
    assert data["organization_id"] == 3
    assert data["selected_date_et"] == "2026-07-27"
    assert data["totals"] == {"total": 94, "completed": 86, "pending": 8, "review": 0}
    assert len(data["completed_ids"]) == 86
    assert len(data["pending_ids"]) == 8
    assert len(set(data["completed_ids"]) & set(data["pending_ids"])) == 0
    assert len(set(data["completed_ids"]) | set(data["pending_ids"])) == 94
    for bid in data["resend_completed_ids"]:
        assert bid in data["completed_ids"]
        assert bid not in data["pending_ids"]
    rush = list(data["rush_status_by_bag"].values())
    assert rush.count("RUSH") == 79
    assert rush.count("NON-RUSH") == 15


@pytest.mark.skipif(
    os.environ.get("RUN_JUL27_COMPLETION_PARITY") != "1",
    reason="Set RUN_JUL27_COMPLETION_PARITY=1 to compare fixture against live DB",
)
def test_jul27_live_db_matches_parity_fixture():
    from datetime import date

    from backend.db import get_db
    from backend.rinse_veewash_shift_day import load_day_bags

    data = _load()
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        bags = load_day_bags(cur, 3, date(2026, 7, 27))
        wf = [b for b in bags if str(b.get("service_type") or "WF").upper() == "WF"]
        completed = sorted(
            str(b["bag_id"]).upper()
            for b in wf
            if str(b.get("effective_status")) == "completed"
        )
        pending = sorted(
            str(b["bag_id"]).upper()
            for b in wf
            if str(b.get("effective_status")) == "pending"
        )
        assert len(wf) == 94
        assert completed == data["completed_ids"]
        assert pending == data["pending_ids"]
    finally:
        cur.close()
        conn.close()
