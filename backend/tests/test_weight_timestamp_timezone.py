"""UTC scrape observation times must not be labeled as naive ET portal times."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.rinse_scan_time import (
    json_safe_rinse,
    serialize_portal_event_for_api,
    serialize_system_datetime_for_api,
    serialize_weight_observation_for_api,
)

UTC = ZoneInfo("UTC")
ET = ZoneInfo("America/New_York")


def test_july_utc_observation_serializes_to_eastern_offset():
    # 12:58 UTC → 08:58 EDT
    raw = datetime(2026, 7, 24, 12, 58, 0)
    out = serialize_weight_observation_for_api(raw)
    assert out == "2026-07-24T08:58:00-04:00"


def test_winter_utc_observation_serializes_to_est():
    # 12:58 UTC → 07:58 EST
    raw = datetime(2026, 1, 15, 12, 58, 0)
    out = serialize_weight_observation_for_api(raw)
    assert out == "2026-01-15T07:58:00-05:00"


def test_dst_spring_forward_boundary():
    # Before 2am ET jump: 06:30 UTC → 01:30 EST
    raw = datetime(2026, 3, 8, 6, 30, 0)
    out = serialize_system_datetime_for_api(raw)
    assert out.endswith("-05:00")
    assert "01:30:00" in out
    # After jump: 07:30 UTC → 03:30 EDT
    after = serialize_system_datetime_for_api(datetime(2026, 3, 8, 7, 30, 0))
    assert after.endswith("-04:00")
    assert "03:30:00" in after


def test_portal_event_naive_et_keeps_eastern_wall():
    # Portal chronology wall 08:24 ET must stay 08:24 with ET offset, not shift.
    raw = datetime(2026, 7, 24, 8, 24, 0)
    out = serialize_portal_event_for_api(raw)
    assert out == "2026-07-24T08:24:00-04:00"


def test_json_safe_rinse_treats_weight_observed_at_as_utc_system():
    payload = {
        "pre_weight_at": datetime(2026, 7, 24, 8, 24, 0),  # ET wall
        "pre_weight_observed_at": datetime(2026, 7, 24, 12, 58, 0),  # UTC
        "weight_observed_at": datetime(2026, 7, 24, 20, 4, 0),  # UTC
    }
    out = json_safe_rinse(payload)
    assert out["pre_weight_at"] == "2026-07-24T08:24:00-04:00"
    assert out["pre_weight_observed_at"] == "2026-07-24T08:58:00-04:00"
    assert out["weight_observed_at"] == "2026-07-24T16:04:00-04:00"


def test_no_naive_timestamp_from_weight_observation_serializer():
    out = serialize_weight_observation_for_api(datetime(2026, 7, 24, 12, 58, 0))
    assert out is not None
    assert ("+" in out[10:] or out.endswith("Z") or "-" in out[10:])
    # Must include numeric offset, not a bare naive wall.
    assert out[-6] in "+-" or out.endswith("Z")
