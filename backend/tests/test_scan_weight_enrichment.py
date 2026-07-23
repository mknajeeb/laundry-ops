"""
Portal weight enrichment: preserve/restore across timeline rebuild + latest-eligible attach.

Events CSV never carries Weight. Portal weight_num arrives later and must attach
to the latest eligible null weight-entry — never to an earlier one, and never
overwriting an already-populated weight_lbs. A timeline rebuild (delete +
reinsert) must not erase previously attached enrichment.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from backend.rinse_scan_weight_enrichment import (
    OUTCOME_CURRENT_LATEST,
    OUTCOME_PRE_NOT_RECOVERABLE,
    OUTCOME_RECOVERED,
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


# ---------------------------------------------------------------------------
# FakeCursor — simulates rinse_bag_scan_events (list of dict rows) plus the
# INFORMATION_SCHEMA probes ensure_scan_weight_enrichment_columns performs.
# Follows the dispatch-by-normalized-sql pattern used elsewhere in the suite
# (test_step1_edit_bag.py / test_scan_timeline_merge_safety.py).
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

        # restore_weight_enrichment (COALESCE update, keyed by dedupe_key)
        if s.startswith("update rinse_bag_scan_events") and "coalesce(weight_lbs" in s:
            lbs, observed_at, source, batch_id, reason, org, bag_id, dedupe_key = params
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
                    matched += 1
            self.rowcount = matched
            self._result = []
            return

        # attach_portal_weight_to_latest_eligible / _apply_backfill_weight (direct set, keyed by id)
        if s.startswith("update rinse_bag_scan_events") and "weight_lbs is null" in s:
            lbs, observed_at, source, batch_id, reason, scan_id, org, bag_id = params
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
            rows.sort(key=lambda r: (r["bag_id"], r.get("scanned_at_parsed"), r.get("scan_index") or 0, r["id"]))
            self._result = rows
            return

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
    }
    row.update(extra)
    return row


# ---------------------------------------------------------------------------
# 1) First event null, portal confirm 13.2 -> first becomes 13.2
# ---------------------------------------------------------------------------


def test_first_event_null_gets_attached_on_portal_confirm():
    cur = _FakeCursor([_row(1, BAG, T0)])
    events = [_row(1, BAG, T0)]

    result = attach_portal_weight_to_latest_eligible(
        cur, ORG, BAG, weight_lbs=13.2, events=events
    )

    assert result["updated"] is True
    assert result["scan_event_id"] == 1
    assert result["weight_lbs"] == 13.2
    assert cur.scan_events[0]["weight_lbs"] == 13.2
    assert cur.scan_events[0]["weight_source"] == "portal_weight_num"


# ---------------------------------------------------------------------------
# 2) Timeline rebuild with the same event coming back null -> 13.2 preserved
# ---------------------------------------------------------------------------


def test_timeline_rebuild_preserves_attached_weight_via_snapshot_restore():
    cur = _FakeCursor(
        [_row(1, BAG, T0, weight_lbs=13.2, weight_source="portal_weight_num", dedupe_key="dkA")]
    )

    preserved = snapshot_weight_enrichment(cur, ORG, [BAG])
    assert preserved[(BAG, "dkA")]["weight_lbs"] == 13.2

    # Simulate delete + reinsert: same dedupe_key, weight_lbs comes back null
    # because the Events CSV export never carries Weight.
    cur.scan_events = [_row(2, BAG, T0, weight_lbs=None, dedupe_key="dkA")]

    restored = restore_weight_enrichment(cur, ORG, preserved)

    assert restored == 1
    assert cur.scan_events[0]["weight_lbs"] == 13.2
    assert cur.scan_events[0]["weight_source"] == "portal_weight_num"


# ---------------------------------------------------------------------------
# 3) + 4) Second weight-entry appears; later portal value goes to the
#         second event only, and the first is left untouched.
# ---------------------------------------------------------------------------


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

    result = attach_portal_weight_to_latest_eligible(cur, ORG, BAG, weight_lbs=22.6, events=events)

    assert result["updated"] is True
    assert result["scan_event_id"] == 2
    first, second = cur.scan_events
    assert first["weight_lbs"] == 13.2
    assert second["weight_lbs"] == 22.6


# ---------------------------------------------------------------------------
# 5) Populated weight + attempted overwrite -> populated value remains
# ---------------------------------------------------------------------------


def test_populated_weight_is_never_overwritten():
    events = [_row(1, BAG, T0, weight_lbs=13.2, dedupe_key="dkA")]
    cur = _FakeCursor(list(events))

    result = attach_portal_weight_to_latest_eligible(cur, ORG, BAG, weight_lbs=99.0, events=events)

    assert result["updated"] is False
    assert result["reason"] == "scan_already_has_weight"
    assert cur.scan_events[0]["weight_lbs"] == 13.2


# ---------------------------------------------------------------------------
# 6) Two null events + only the current portal value -> attaches only to the
#    latest (the 42EN4J3VRB "do not attach 22.6 to the first event" rule).
# ---------------------------------------------------------------------------


def test_two_null_events_attach_only_to_latest_never_first():
    events = [
        _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
        _row(2, BAG, T1, weight_lbs=None, dedupe_key="dkB"),
    ]
    cur = _FakeCursor(list(events))

    result = attach_portal_weight_to_latest_eligible(cur, ORG, BAG, weight_lbs=22.6, events=events)

    assert result["updated"] is True
    assert result["scan_event_id"] == 2
    first, second = cur.scan_events
    assert first["weight_lbs"] is None, "22.6 must never attach to the first event of 42EN4J3VRB"
    assert second["weight_lbs"] == 22.6


# ---------------------------------------------------------------------------
# 7) No historical evidence for the first event -> stays null, manager
#    correction required (classify_and_backfill_bag / production 42EN4J3VRB).
# ---------------------------------------------------------------------------


def test_classify_backfill_no_historical_evidence_requires_manager_correction():
    weight_events = [
        _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
        _row(2, BAG, T2, weight_lbs=None, dedupe_key="dkB"),
    ]
    cur = _FakeCursor(list(weight_events))

    # Only the current/final portal observation exists, confirmed after the
    # second (latest) weight-entry scan — there is no historical observation
    # between W1 and W2 to recover W1 from.
    observations = [
        {"weight_num": 22.6, "observed_at": T2, "upload_batch_id": 501},
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

    # Applied (dry_run=False): second event gets 22.6, first stays null.
    first, second = cur.scan_events
    assert first["weight_lbs"] is None, "22.6 must never attach to the first event of 42EN4J3VRB"
    assert second["weight_lbs"] == 22.6


def test_classify_backfill_recovers_first_event_from_historical_observation():
    weight_events = [
        _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
        _row(2, BAG, T2, weight_lbs=None, dedupe_key="dkB"),
    ]
    cur = _FakeCursor(list(weight_events))

    # A historical portal batch confirmed 13.2 strictly between W1 (T0) and
    # W2 (T2) — that's real evidence for the pre-clean weight.
    observations = [
        {"weight_num": 13.2, "observed_at": T1, "upload_batch_id": 500},
        {"weight_num": 22.6, "observed_at": T2, "upload_batch_id": 501},
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
    assert first["weight_source"] == "portal_weight_num_historical"
    assert second["weight_source"] == "portal_weight_num"


def test_classify_backfill_dry_run_performs_no_writes():
    weight_events = [
        _row(1, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
        _row(2, BAG, T2, weight_lbs=None, dedupe_key="dkB"),
    ]
    cur = _FakeCursor(list(weight_events))
    observations = [{"weight_num": 22.6, "observed_at": T2, "upload_batch_id": 501}]

    with patch(
        "backend.rinse_scan_weight_enrichment._load_portal_weight_observations_for_bag",
        return_value=observations,
    ):
        result = classify_and_backfill_bag(cur, ORG, BAG, dry_run=True)

    assert result["dry_run"] is True
    # No mutation happened — dry_run only classifies.
    assert cur.scan_events[0]["weight_lbs"] is None
    assert cur.scan_events[1]["weight_lbs"] is None


# ---------------------------------------------------------------------------
# 8) Midnight rebuild simulation: preserve map survives delete+reinsert for
#    multiple bags/rows at once.
# ---------------------------------------------------------------------------


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

    # Simulate the nightly portal export rebuild: delete all rows for both
    # bags, then reinsert the same logical rows (same dedupe_key) with a null
    # weight — exactly what happens because the Events CSV has no Weight col.
    cur.scan_events = [
        _row(10, BAG, T0, weight_lbs=None, dedupe_key="dkA"),
        _row(11, BAG, T2, weight_lbs=None, dedupe_key="dkB"),
        _row(12, bag2, T0, weight_lbs=None, dedupe_key="dkC"),
    ]

    restored = restore_weight_enrichment(cur, ORG, preserved)

    assert restored == 3
    by_dk = {r["dedupe_key"]: r for r in cur.scan_events}
    assert by_dk["dkA"]["weight_lbs"] == 13.2
    assert by_dk["dkB"]["weight_lbs"] == 22.6
    assert by_dk["dkC"]["weight_lbs"] == 9.0


# ---------------------------------------------------------------------------
# 9) Day snapshot pre/post from the two enriched events (resolve_weight_entry_pair)
# ---------------------------------------------------------------------------


def test_resolve_weight_entry_pair_reflects_enriched_pre_post():
    from backend.rinse_veewash_review import resolve_weight_entry_pair

    events = [
        _row(1, BAG, T0, weight_lbs=13.2, dedupe_key="dkA"),
        _row(2, BAG, T2, weight_lbs=22.6, dedupe_key="dkB"),
    ]
    out = resolve_weight_entry_pair(events)
    assert out["pre_weight_lbs"] == 13.2
    assert out["post_weight_lbs"] == 22.6


# ---------------------------------------------------------------------------
# merge_scan_events_from_upload wires snapshot/restore around the delete
# ---------------------------------------------------------------------------


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
        return 1

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
