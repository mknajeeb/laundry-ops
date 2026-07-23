"""
Portal weight enrichment: preserve/restore across timeline rebuild + interval attach.

Events CSV never carries Weight. Portal weight_num arrives later (Presence Run
Rows / confirm) and must attach via chronological intervals (PRE / POST /
WEIGHT_RECHECK). A timeline rebuild (delete + reinsert) must not erase
previously attached enrichment; restore reports unmatched dedupe keys.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from backend.rinse_scan_weight_enrichment import (
    OUTCOME_CURRENT_LATEST,
    OUTCOME_PRE_NOT_RECOVERABLE,
    OUTCOME_RECOVERED,
    WEIGHT_ROLE_PRE,
    WEIGHT_ROLE_POST,
    WEIGHT_ROLE_RECHECK,
    attach_observations_to_weight_events,
    attach_portal_weight_to_latest_eligible,
    classify_and_backfill_bag,
    restore_weight_enrichment,
    snapshot_weight_enrichment,
)

ORG = 3
BAG = "42EN4J3VRB"
T0 = datetime(2026, 7, 22, 8, 0, 0)
T1 = datetime(2026, 7, 22, 9, 0, 0)
T2 = datetime(2026, 7, 22, 14, 0, 0)
T3 = datetime(2026, 7, 22, 16, 0, 0)


# ---------------------------------------------------------------------------
# FakeCursor — simulates rinse_bag_scan_events (list of dict rows) plus the
# INFORMATION_SCHEMA probes ensure_scan_weight_enrichment_columns performs.
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[dict] | None = None):
        self.scan_events: list[dict] = rows or []
        self._result: list = []
        self.rowcount = 0

    @staticmethod
    def _norm(sql) -> str:
        return " ".join(str(sql).split()).lower()

    def execute(self, sql, params=None):
        params = tuple(params or ())
        s = self._norm(sql)

        if "information_schema" in s or "show tables" in s:
            self._result = [{"c": 1}]
            return
        if s.startswith("create table") or s.startswith("alter table"):
            self._result = []
            return

        # snapshot_weight_enrichment
        if (
            "from rinse_bag_scan_events" in s
            and "weight_lbs is not null" in s
            and "dedupe_key is not null" in s
        ):
            org = int(params[0])
            bag_ids = set(params[1:])
            rows = [
                dict(r)
                for r in self.scan_events
                if r["organization_id"] == org
                and r["bag_id"] in bag_ids
                and r.get("weight_lbs") is not None
                and r.get("dedupe_key")
            ]
            self._result = rows
            return

        # restore: lookup by dedupe_key
        if (
            "from rinse_bag_scan_events" in s
            and "dedupe_key = %s" in s
            and "select id, weight_lbs" in s
        ):
            org, bag_id, dedupe_key = params
            rows = [
                dict(r)
                for r in self.scan_events
                if r["organization_id"] == int(org)
                and r["bag_id"] == bag_id
                and r.get("dedupe_key") == dedupe_key
            ]
            self._result = rows[:1]
            return

        # restore_weight_enrichment (COALESCE update, keyed by dedupe_key)
        if s.startswith("update rinse_bag_scan_events") and "coalesce(weight_lbs" in s:
            (
                lbs,
                observed_at,
                source,
                batch_id,
                reason,
                presence_run_id,
                presence_run_row_id,
                weight_role,
                org,
                bag_id,
                dedupe_key,
            ) = params
            matched = 0
            for r in self.scan_events:
                if (
                    r["organization_id"] == int(org)
                    and r["bag_id"] == bag_id
                    and r.get("dedupe_key") == dedupe_key
                    and r.get("weight_lbs") is None
                ):
                    r["weight_lbs"] = lbs
                    r["weight_observed_at"] = r.get("weight_observed_at") or observed_at
                    r["weight_source"] = r.get("weight_source") or source
                    r["weight_attach_batch_id"] = r.get("weight_attach_batch_id") or batch_id
                    r["weight_attach_reason"] = r.get("weight_attach_reason") or reason
                    r["weight_presence_run_id"] = (
                        r.get("weight_presence_run_id") or presence_run_id
                    )
                    r["weight_presence_run_row_id"] = (
                        r.get("weight_presence_run_row_id") or presence_run_row_id
                    )
                    r["weight_role"] = r.get("weight_role") or weight_role
                    matched += 1
            self.rowcount = matched
            self._result = []
            return

        # attach / interval apply (direct set, keyed by id)
        if s.startswith("update rinse_bag_scan_events") and "weight_lbs is null" in s:
            (
                lbs,
                observed_at,
                source,
                batch_id,
                reason,
                presence_run_id,
                presence_run_row_id,
                weight_role,
                scan_id,
                org,
                bag_id,
            ) = params
            matched = 0
            for r in self.scan_events:
                if (
                    r["id"] == int(scan_id)
                    and r["organization_id"] == int(org)
                    and r["bag_id"] == bag_id
                    and r.get("weight_lbs") is None
                ):
                    r["weight_lbs"] = lbs
                    r["weight_observed_at"] = observed_at
                    r["weight_source"] = source
                    r["weight_attach_batch_id"] = batch_id
                    r["weight_attach_reason"] = reason
                    r["weight_presence_run_id"] = presence_run_id
                    r["weight_presence_run_row_id"] = presence_run_row_id
                    r["weight_role"] = weight_role
                    matched += 1
            self.rowcount = matched
            self._result = []
            return

        # _load_scan_events_for_bags (classify_and_backfill_bag's events=None path)
        if "from rinse_bag_scan_events" in s and "order by bag_id, scanned_at_parsed" in s:
            org = int(params[0])
            bag_ids = set(params[1:])
            rows = [
                dict(r)
                for r in self.scan_events
                if r["organization_id"] == org and r["bag_id"] in bag_ids
            ]
            rows.sort(
                key=lambda r: (
                    r["bag_id"],
                    r.get("scanned_at_parsed"),
                    r.get("scan_index") or 0,
                    r["id"],
                )
            )
            self._result = rows
            return

        # manager-correction / presence observation probes → empty
        self._result = []

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


def _row(scan_id, bag_id, ts, *, purpose="weight-entry", weight_lbs=None, dedupe_key=None, **extra):
    row = {
        "id": scan_id,
        "organization_id": ORG,
        "bag_id": bag_id,
        "dedupe_key": dedupe_key or f"dk{scan_id}",
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "scan_index": scan_id,
        "weight_lbs": weight_lbs,
        "weight_observed_at": None,
        "weight_source": None,
        "weight_attach_batch_id": None,
        "weight_attach_reason": None,
        "weight_presence_run_id": None,
        "weight_presence_run_row_id": None,
        "weight_role": None,
    }
    row.update(extra)
    return row


# ---------------------------------------------------------------------------
# Confirm-path / interval attach
# ---------------------------------------------------------------------------


def test_first_event_null_gets_attached_on_portal_confirm():
    cur = _FakeCursor([_row(1, BAG, T0)])
    events = [_row(1, BAG, T0)]

    result = attach_portal_weight_to_latest_eligible(
        cur, ORG, BAG, weight_lbs=13.2, events=events, portal_observed_at=T1
    )

    assert result["updated"] is True
    assert result["scan_event_id"] == 1
    assert result["weight_lbs"] == 13.2
    assert result["weight_role"] == WEIGHT_ROLE_PRE
    assert cur.scan_events[0]["weight_lbs"] == 13.2
    assert cur.scan_events[0]["weight_source"] == "portal_weight_num"


def test_timeline_rebuild_preserves_attached_weight_via_snapshot_restore():
    cur = _FakeCursor(
        [
            _row(
                1,
                BAG,
                T0,
                weight_lbs=13.2,
                weight_source="portal_weight_num",
                weight_role=WEIGHT_ROLE_PRE,
                weight_presence_run_id=10,
                weight_presence_run_row_id=100,
                dedupe_key="dkA",
            )
        ]
    )

    preserved = snapshot_weight_enrichment(cur, ORG, [BAG])
    assert preserved[(BAG, "dkA")]["weight_lbs"] == 13.2
    assert preserved[(BAG, "dkA")]["weight_role"] == WEIGHT_ROLE_PRE
    assert preserved[(BAG, "dkA")]["weight_presence_run_id"] == 10

    cur.scan_events = [_row(2, BAG, T0, weight_lbs=None, dedupe_key="dkA")]

    restored = restore_weight_enrichment(cur, ORG, preserved)

    assert restored["updated"] == 1
    assert restored["unmatched"] == []
    assert cur.scan_events[0]["weight_lbs"] == 13.2
    assert cur.scan_events[0]["weight_source"] == "portal_weight_num"
    assert cur.scan_events[0]["weight_role"] == WEIGHT_ROLE_PRE
    assert cur.scan_events[0]["weight_presence_run_id"] == 10


def test_restore_reports_unmatched_when_dedupe_key_missing():
    cur = _FakeCursor([_row(1, BAG, T0, weight_lbs=None, dedupe_key="dkOther")])
    preserved = {
        (BAG, "dkMissing"): {
            "weight_lbs": 13.2,
            "weight_source": "presence_run_weight_num",
            "weight_role": WEIGHT_ROLE_PRE,
        }
    }
    restored = restore_weight_enrichment(cur, ORG, preserved)
    assert restored["updated"] == 0
    assert len(restored["unmatched"]) == 1
    assert restored["unmatched"][0]["reason"] == "dedupe_key_not_found"
    assert restored["unmatched"][0]["weight_lbs"] == 13.2
    assert cur.scan_events[0]["weight_lbs"] is None


def test_second_weight_entry_created_first_stays_attached_second_null():
    cur = _FakeCursor(
        [
            _row(1, BAG, T0, weight_lbs=13.2, dedupe_key="dkA"),
            _row(2, BAG, T1, weight_lbs=None, dedupe_key="dkB"),
        ]
    )
    assert cur.scan_events[0]["weight_lbs"] == 13.2
    assert cur.scan_events[1]["weight_lbs"] is None


def test_later_portal_value_attaches_to_second_event_first_untouched():
    events = [
        _row(1, BAG, T0, weight_lbs=13.2, dedupe_key="dkA"),
        _row(2, BAG, T1, weight_lbs=None, dedupe_key="dkB"),
    ]
    cur = _FakeCursor(list(events))

    result = attach_portal_weight_to_latest_eligible(
        cur, ORG, BAG, weight_lbs=22.6, events=events, portal_observed_at=T2
    )

    assert result["updated"] is True
    assert result["scan_event_id"] == 2
    assert result["weight_role"] == WEIGHT_ROLE_POST
    first, second = cur.scan_events
    assert first["weight_lbs"] == 13.2
    assert second["weight_lbs"] == 22.6


def test_populated_weight_is_never_overwritten():
    events = [_row(1, BAG, T0, weight_lbs=13.2, dedupe_key="dkA")]
    cur = _FakeCursor(list(events))

    result = attach_portal_weight_to_latest_eligible(
        cur, ORG, BAG, weight_lbs=99.0, events=events, portal_observed_at=T1
    )

    assert result["updated"] is False
    assert result["reason"] == "scan_already_has_weight"
    assert cur.scan_events[0]["weight_lbs"] == 13.2


def test_two_null_events_attach_only_to_latest_never_first():
    events = [
        _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
        _row(2, BAG, T1, weight_lbs=None, dedupe_key="dkB"),
    ]
    cur = _FakeCursor(list(events))

    # Observation at/after POST timestamp must not backfill PRE.
    result = attach_portal_weight_to_latest_eligible(
        cur, ORG, BAG, weight_lbs=22.6, events=events, portal_observed_at=T1
    )

    assert result["updated"] is True
    assert result["scan_event_id"] == 2
    first, second = cur.scan_events
    assert first["weight_lbs"] is None, "22.6 must never attach to the first event of 42EN4J3VRB"
    assert second["weight_lbs"] == 22.6


def test_interval_attach_same_numeric_to_pre_and_post_from_different_obs():
    events = [
        _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
        _row(2, BAG, T2, weight_lbs=None, dedupe_key="dkB"),
    ]
    cur = _FakeCursor([dict(e) for e in events])
    observations = [
        {"weight_num": 23.6, "observed_at": T1, "presence_run_id": 1, "presence_run_row_id": 11},
        {"weight_num": 23.6, "observed_at": T3, "presence_run_id": 2, "presence_run_row_id": 22},
    ]
    result = attach_observations_to_weight_events(
        cur, ORG, BAG, observations=observations, events=events, dry_run=False
    )
    assert result["updated_count"] == 2
    assert cur.scan_events[0]["weight_lbs"] == 23.6
    assert cur.scan_events[0]["weight_role"] == WEIGHT_ROLE_PRE
    assert cur.scan_events[1]["weight_lbs"] == 23.6
    assert cur.scan_events[1]["weight_role"] == WEIGHT_ROLE_POST


def test_third_weight_entry_is_weight_recheck_not_post():
    events = [
        _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
        _row(2, BAG, T1, weight_lbs=None, dedupe_key="dkB"),
        _row(3, BAG, T2, weight_lbs=None, dedupe_key="dkC"),
    ]
    cur = _FakeCursor([dict(e) for e in events])
    observations = [
        {"weight_num": 10.0, "observed_at": T0, "presence_run_id": 1, "presence_run_row_id": 1},
        {"weight_num": 20.0, "observed_at": T1, "presence_run_id": 2, "presence_run_row_id": 2},
        {"weight_num": 30.0, "observed_at": T3, "presence_run_id": 3, "presence_run_row_id": 3},
    ]
    result = attach_observations_to_weight_events(
        cur, ORG, BAG, observations=observations, events=events, dry_run=False
    )
    roles = [a["weight_role"] for a in result["attached"]]
    assert roles == [WEIGHT_ROLE_PRE, WEIGHT_ROLE_POST, WEIGHT_ROLE_RECHECK]
    assert cur.scan_events[2]["weight_role"] == WEIGHT_ROLE_RECHECK
    assert cur.scan_events[2]["weight_lbs"] == 30.0


# ---------------------------------------------------------------------------
# classify_and_backfill_bag (presence observations + interval attach)
# ---------------------------------------------------------------------------


def test_classify_backfill_no_historical_evidence_requires_manager_correction():
    weight_events = [
        _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
        _row(2, BAG, T2, weight_lbs=None, dedupe_key="dkB"),
    ]
    cur = _FakeCursor(list(weight_events))

    observations = [
        {"weight_num": 22.6, "observed_at": T2, "presence_run_id": 501, "presence_run_row_id": 1},
    ]

    with patch(
        "backend.rinse_scan_weight_enrichment._load_portal_weight_observations_for_bag",
        return_value=observations,
    ):
        result = classify_and_backfill_bag(cur, ORG, BAG, dry_run=False)

    events_by_pos = {e["position"]: e for e in result["events"]}
    assert events_by_pos[1]["outcome"] == OUTCOME_CURRENT_LATEST
    assert events_by_pos[1]["weight_lbs"] == 22.6
    assert events_by_pos[0]["outcome"] == OUTCOME_PRE_NOT_RECOVERABLE
    assert events_by_pos[0]["manager_correction_required"] is True
    assert result["manager_correction_required_count"] == 1

    first, second = cur.scan_events
    assert first["weight_lbs"] is None, "22.6 must never attach to the first event of 42EN4J3VRB"
    assert second["weight_lbs"] == 22.6


def test_classify_backfill_recovers_first_event_from_historical_observation():
    weight_events = [
        _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
        _row(2, BAG, T2, weight_lbs=None, dedupe_key="dkB"),
    ]
    cur = _FakeCursor(list(weight_events))

    observations = [
        {"weight_num": 13.2, "observed_at": T1, "presence_run_id": 500, "presence_run_row_id": 1},
        {"weight_num": 22.6, "observed_at": T2, "presence_run_id": 501, "presence_run_row_id": 2},
    ]

    with patch(
        "backend.rinse_scan_weight_enrichment._load_portal_weight_observations_for_bag",
        return_value=observations,
    ):
        result = classify_and_backfill_bag(cur, ORG, BAG, dry_run=False)

    events_by_pos = {e["position"]: e for e in result["events"]}
    assert events_by_pos[0]["outcome"] == OUTCOME_RECOVERED
    assert events_by_pos[0]["weight_lbs"] == 13.2
    assert events_by_pos[1]["outcome"] == OUTCOME_CURRENT_LATEST
    assert events_by_pos[1]["weight_lbs"] == 22.6

    first, second = cur.scan_events
    assert first["weight_lbs"] == 13.2
    assert second["weight_lbs"] == 22.6
    assert first["weight_source"] == "presence_run_weight_num"
    assert second["weight_source"] == "presence_run_weight_num"


def test_classify_backfill_dry_run_performs_no_writes():
    weight_events = [
        _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
        _row(2, BAG, T2, weight_lbs=None, dedupe_key="dkB"),
    ]
    cur = _FakeCursor(list(weight_events))
    observations = [
        {"weight_num": 22.6, "observed_at": T2, "presence_run_id": 501, "presence_run_row_id": 1}
    ]

    with patch(
        "backend.rinse_scan_weight_enrichment._load_portal_weight_observations_for_bag",
        return_value=observations,
    ):
        result = classify_and_backfill_bag(cur, ORG, BAG, dry_run=True)

    assert result["dry_run"] is True
    assert cur.scan_events[0]["weight_lbs"] is None
    assert cur.scan_events[1]["weight_lbs"] is None


def test_midnight_rebuild_preserve_map_survives_multi_row_delete_reinsert():
    bag2 = "BAGWF2"
    cur = _FakeCursor(
        [
            _row(1, BAG, T0, weight_lbs=13.2, dedupe_key="dkA"),
            _row(2, BAG, T2, weight_lbs=22.6, dedupe_key="dkB"),
            _row(3, bag2, T0, weight_lbs=9.0, dedupe_key="dkC"),
        ]
    )

    preserved = snapshot_weight_enrichment(cur, ORG, [BAG, bag2])
    assert len(preserved) == 3

    cur.scan_events = [
        _row(10, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
        _row(11, BAG, T2, weight_lbs=None, dedupe_key="dkB"),
        _row(12, bag2, T0, weight_lbs=None, dedupe_key="dkC"),
    ]

    restored = restore_weight_enrichment(cur, ORG, preserved)

    assert restored["updated"] == 3
    assert restored["unmatched"] == []
    by_dk = {r["dedupe_key"]: r for r in cur.scan_events}
    assert by_dk["dkA"]["weight_lbs"] == 13.2
    assert by_dk["dkB"]["weight_lbs"] == 22.6
    assert by_dk["dkC"]["weight_lbs"] == 9.0


def test_resolve_weight_entry_pair_reflects_enriched_pre_post():
    from backend.rinse_veewash_review import resolve_weight_entry_pair

    events = [
        _row(1, BAG, T0, weight_lbs=13.2, dedupe_key="dkA"),
        _row(2, BAG, T2, weight_lbs=22.6, dedupe_key="dkB"),
    ]
    out = resolve_weight_entry_pair(events)
    assert out["pre_weight_lbs"] == 13.2
    assert out["post_weight_lbs"] == 22.6


def test_merge_scan_events_from_upload_invokes_snapshot_and_restore():
    import pandas as pd

    from backend.rinse_bag_registry import merge_scan_events_from_upload

    events_df = pd.DataFrame(
        [
            {
                "Bag ID": BAG,
                "Scan Index": "1",
                "Rack": "",
                "Time Scanned": "Wednesday, July 22, 2026 8:00 AM",
                "User": "Evelin",
                "Purpose": "Weight-Entry",
                "Last Location": "",
                "Last Scan": "",
            }
        ]
    )

    calls: dict = {}

    def _fake_snapshot(cursor, org, bag_ids):
        calls["snapshot_args"] = (org, tuple(bag_ids))
        return {(BAG, "dkA"): {"weight_lbs": 13.2}}

    def _fake_restore(cursor, org, preserved):
        calls["restore_args"] = (org, dict(preserved))
        return {"updated": 1, "unmatched": [], "skipped_already_populated": 0}

    with patch("backend.rinse_bag_registry.ensure_rinse_bag_tables"), patch(
        "backend.rinse_bag_registry.ensure_rinse_bag_scan_events_dedupe_schema"
    ), patch(
        "backend.rinse_bag_operational_owner.filter_bag_ids_for_operational_write",
        return_value=([BAG], []),
    ), patch(
        "backend.rinse_bag_registry._persistent_scan_bounds_for_bags",
        return_value={BAG: (None, 0)},
    ), patch(
        "backend.rinse_bag_registry.delete_persistent_scan_events_for_bags", return_value=0
    ) as mock_delete, patch(
        "backend.rinse_bag_registry.upsert_scan_event_row", return_value="inserted"
    ), patch(
        "backend.rinse_scan_weight_enrichment.snapshot_weight_enrichment",
        side_effect=_fake_snapshot,
    ) as mock_snapshot, patch(
        "backend.rinse_scan_weight_enrichment.restore_weight_enrichment",
        side_effect=_fake_restore,
    ) as mock_restore:
        cur = _FakeCursor()
        result = merge_scan_events_from_upload(
            cur, ORG, 999, events_df, "events.csv", replace_existing=True
        )

    mock_snapshot.assert_called_once()
    mock_delete.assert_called_once()
    mock_restore.assert_called_once()
    assert calls["snapshot_args"][0] == ORG
    assert BAG in calls["snapshot_args"][1]
    assert calls["restore_args"][1] == {(BAG, "dkA"): {"weight_lbs": 13.2}}
    assert result["weight_enrichment_preserved"] == 1
    assert result["weight_enrichment_restored"] == 1
    assert result["weight_enrichment_restore_stats"]["updated"] == 1
