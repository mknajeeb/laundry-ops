"""Current-cycle PRE/POST weight resolver — stabilization suite."""

from __future__ import annotations

from datetime import date, datetime

from backend.rinse_current_cycle_weight import (
    STATUS_CONFIRMED,
    STATUS_EQUAL_VALUES_CONFIRMED,
    STATUS_MANUAL_CORRECTION,
    STATUS_PROVISIONAL,
    STATUS_WAITING_FOR_POST_VALUE,
    STATUS_CONFLICTING_OBSERVATIONS,
    classify_post_repair,
    resolve_current_cycle_weights,
    select_current_cycle_weight_events,
)

DAY = date(2026, 7, 29)


def _ev(purpose, ts, *, lbs=None, user="Op", eid=1, rack=None, **extra):
    row = {
        "id": eid,
        "purpose": purpose,
        "scanned_at_parsed": ts,
        "user_name": user,
        "weight_lbs": lbs,
        "rack": rack,
    }
    row.update(extra)
    return row


def _obs(ts, lbs, run=1, row_id=1):
    return {
        "observed_at": ts,
        "weight_num": lbs,
        "presence_run_id": run,
        "presence_run_row_id": row_id,
    }


def _cycle_base(*, old_weights=True):
    """Standard Jul 29 cycle with optional prior-cycle weight entries."""
    events = []
    if old_weights:
        events.extend(
            [
                _ev("sent-to-vendor", datetime(2026, 6, 20, 5, 0), eid=1),
                _ev("move-bag", datetime(2026, 6, 20, 6, 0), eid=2, rack="VeeWash Dirty"),
                _ev("weight-entry", datetime(2026, 6, 20, 7, 0), eid=3, lbs=99.0, user="OldPre"),
                _ev("garments-reviewed", datetime(2026, 6, 20, 10, 0), eid=4),
                _ev("weight-entry", datetime(2026, 6, 20, 10, 5), eid=5, lbs=88.0, user="OldPost"),
            ]
        )
    events.extend(
        [
            _ev("sent-to-vendor", datetime(2026, 7, 29, 5, 0), eid=10),
            _ev("move-bag", datetime(2026, 7, 29, 5, 30), eid=11, rack="VeeWash Dirty"),
            _ev("weight-entry", datetime(2026, 7, 29, 6, 0), eid=12, user="Varun"),  # PRE
            _ev("garments-reviewed", datetime(2026, 7, 29, 10, 0), eid=13),
            _ev("weight-entry", datetime(2026, 7, 29, 10, 5), eid=14, user="Folder"),  # POST
        ]
    )
    return events


def test_old_cycle_weight_entries_ignored():
    events = _cycle_base(old_weights=True)
    selected = select_current_cycle_weight_events(events, selected_date_et=DAY)
    assert selected["pre_event"]["id"] == 12
    assert selected["post_event"]["id"] == 14
    assert selected["pre_event"]["user_name"] == "Varun"
    # Lifetime ordinal would have picked id 3 / 5.
    assert selected["pre_event"]["id"] != 3
    assert selected["post_event"]["id"] != 5


def test_latest_pre_review_weight_chosen():
    events = _cycle_base(old_weights=False)
    events.insert(
        -2,
        _ev("weight-entry", datetime(2026, 7, 29, 7, 0), eid=15, user="MidPre"),
    )
    selected = select_current_cycle_weight_events(events, selected_date_et=DAY)
    assert selected["pre_event"]["id"] == 15
    assert selected["pre_event"]["user_name"] == "MidPre"


def test_earliest_post_review_weight_chosen():
    events = _cycle_base(old_weights=False)
    events.append(
        _ev("weight-entry", datetime(2026, 7, 29, 11, 0), eid=16, user="LaterPost")
    )
    selected = select_current_cycle_weight_events(events, selected_date_et=DAY)
    assert selected["post_event"]["id"] == 14
    assert selected["post_event"]["user_name"] == "Folder"


def test_lifetime_ordinal_not_used_for_lbs_when_observations_present():
    events = _cycle_base(old_weights=True)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 18.3, run=1),
        _obs(datetime(2026, 7, 29, 12, 0), 11.7, run=2),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.pre_weight_lbs == 18.3
    assert resolved.post_weight_lbs == 11.7
    assert resolved.pre_weight_event_id == 12
    assert resolved.post_weight_event_id == 14
    # Must not project old-cycle 99/88.
    assert resolved.pre_weight_lbs != 99.0
    assert resolved.post_weight_lbs != 88.0


def test_portal_still_showing_pre_after_post_scan_stays_provisional():
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 23.5, run=1),
        _obs(datetime(2026, 7, 29, 10, 30), 23.5, run=2),  # after POST, still PRE
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.pre_weight_lbs == 23.5
    assert resolved.post_weight_lbs == 23.5
    assert resolved.post_resolution_status == STATUS_PROVISIONAL


def test_later_portal_value_corrects_post():
    """Anonymized stale-equal fixture: 18RRTGC65A pattern."""
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 23.5, run=1),
        _obs(datetime(2026, 7, 29, 10, 30), 23.5, run=2),
        _obs(datetime(2026, 7, 29, 13, 0), 21.5, run=3),
        _obs(datetime(2026, 7, 29, 14, 0), 21.5, run=4),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.pre_weight_lbs == 23.5
    assert resolved.post_weight_lbs == 21.5
    assert resolved.post_resolution_status == STATUS_CONFIRMED
    assert "differs_from_pre" in (resolved.resolution_reason or "")


def test_stale_fill_once_regression_not_frozen():
    events = _cycle_base(old_weights=False)
    # Seed POST event with stale PRE lbs (legacy fill-once).
    for ev in events:
        if ev["id"] == 12:
            ev["weight_lbs"] = 23.5
        if ev["id"] == 14:
            ev["weight_lbs"] = 23.5
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 23.5, run=1),
        _obs(datetime(2026, 7, 29, 10, 30), 23.5, run=2),
        _obs(datetime(2026, 7, 29, 13, 0), 21.5, run=3),
        _obs(datetime(2026, 7, 29, 14, 0), 21.5, run=4),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.post_weight_lbs == 21.5


def test_legitimate_pre_equals_post():
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 12.5, run=1),
        _obs(datetime(2026, 7, 29, 10, 30), 12.5, run=2),
        _obs(datetime(2026, 7, 29, 11, 30), 12.5, run=3),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.pre_weight_lbs == 12.5
    assert resolved.post_weight_lbs == 12.5
    assert resolved.post_resolution_status == STATUS_EQUAL_VALUES_CONFIRMED


def test_multiple_pre_review_and_post_review_scans():
    events = [
        _ev("sent-to-vendor", datetime(2026, 7, 29, 5, 0), eid=1),
        _ev("move-bag", datetime(2026, 7, 29, 5, 30), eid=2, rack="Rinse Zipvan"),
        _ev("weight-entry", datetime(2026, 7, 29, 6, 0), eid=3, user="A"),
        _ev("weight-entry", datetime(2026, 7, 29, 7, 0), eid=4, user="B"),
        _ev("garments-reviewed", datetime(2026, 7, 29, 10, 0), eid=5),
        _ev("weight-entry", datetime(2026, 7, 29, 10, 5), eid=6, user="C"),
        _ev("weight-entry", datetime(2026, 7, 29, 10, 10), eid=7, user="D"),
    ]
    selected = select_current_cycle_weight_events(events, selected_date_et=DAY)
    assert selected["pre_event"]["id"] == 4
    assert selected["post_event"]["id"] == 6


def test_manual_correction_precedence():
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 10.8, run=1),
        _obs(datetime(2026, 7, 29, 10, 30), 10.8, run=2),
    ]
    resolved = resolve_current_cycle_weights(
        events,
        selected_date_et=DAY,
        observations=observations,
        manual_post_lbs=4.8,
    )
    assert resolved.post_weight_lbs == 4.8
    assert resolved.post_resolution_status == STATUS_MANUAL_CORRECTION
    assert resolved.corrected_post_weight_lbs == 4.8


def test_prior_cycle_blank_case_recovers_current_lbs():
    """Anonymized 52QTT5IR0J pattern: old null ordinal events, current cycle has lbs."""
    events = [
        _ev("weight-entry", datetime(2026, 7, 15, 6, 0), eid=1, lbs=None),
        _ev("weight-entry", datetime(2026, 7, 15, 12, 0), eid=2, lbs=None),
        _ev("sent-to-vendor", datetime(2026, 7, 29, 4, 0), eid=3),
        _ev("move-bag", datetime(2026, 7, 29, 5, 0), eid=4, rack="VeeWash Dirty"),
        _ev("weight-entry", datetime(2026, 7, 29, 5, 30), eid=5, user="Varun"),
        _ev("garments-reviewed", datetime(2026, 7, 29, 15, 0), eid=6),
        _ev("weight-entry", datetime(2026, 7, 29, 15, 5), eid=7, user="Folder"),
    ]
    observations = [
        _obs(datetime(2026, 7, 29, 9, 0), 18.1, run=1),
        _obs(datetime(2026, 7, 29, 16, 0), 18.1, run=2),
        _obs(datetime(2026, 7, 29, 17, 0), 18.1, run=3),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.pre_weight_lbs == 18.1
    assert resolved.post_weight_lbs == 18.1
    assert resolved.pre_weight_event_id == 5
    assert resolved.post_weight_event_id == 7


def test_comforter_independence_same_rules():
    """Comforter bags use the same resolver — no WI-specific weight path."""
    events = _cycle_base(old_weights=False)
    events.insert(
        -2,
        _ev("create-workitem-bulk", datetime(2026, 7, 29, 7, 30), eid=20, user="Francis"),
    )
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 22.2, run=1),
        _obs(datetime(2026, 7, 29, 12, 0), 15.9, run=2),
        _obs(datetime(2026, 7, 29, 13, 0), 15.9, run=3),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.pre_weight_lbs == 22.2
    assert resolved.post_weight_lbs == 15.9
    assert resolved.post_resolution_status == STATUS_CONFIRMED


def test_bath_mat_independence_same_rules():
    events = _cycle_base(old_weights=False)
    events.insert(
        -2,
        _ev("create-workitem-bulk", datetime(2026, 7, 29, 7, 30), eid=21, user="Francis"),
    )
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 16.1, run=1),
        _obs(datetime(2026, 7, 29, 12, 0), 7.8, run=2),
        _obs(datetime(2026, 7, 29, 13, 0), 7.8, run=3),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.pre_weight_lbs == 16.1
    assert resolved.post_weight_lbs == 7.8


def test_repeated_scrape_idempotency():
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 18.3, run=1),
        _obs(datetime(2026, 7, 29, 12, 0), 11.7, run=2),
        _obs(datetime(2026, 7, 29, 13, 0), 11.7, run=3),
        _obs(datetime(2026, 7, 29, 14, 0), 11.7, run=4),
    ]
    a = resolve_current_cycle_weights(events, selected_date_et=DAY, observations=observations)
    b = resolve_current_cycle_weights(events, selected_date_et=DAY, observations=observations)
    assert a.as_weight_info()["pre_weight_lbs"] == b.as_weight_info()["pre_weight_lbs"]
    assert a.as_weight_info()["post_weight_lbs"] == b.as_weight_info()["post_weight_lbs"]
    assert a.post_resolution_status == b.post_resolution_status


def test_surface_agreement_shape():
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 18.3, run=1),
        _obs(datetime(2026, 7, 29, 12, 0), 11.7, run=2),
        _obs(datetime(2026, 7, 29, 13, 0), 11.7, run=3),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    info = resolved.as_weight_info()
    # Shift Monitor / AV / EP consume the same keys.
    for key in (
        "pre_weight_lbs",
        "post_weight_lbs",
        "pre_weight_at",
        "post_weight_at",
        "pre_resolution_status",
        "post_resolution_status",
    ):
        assert key in info
    assert info["pre_weight_lbs"] == 18.3
    assert info["post_weight_lbs"] == 11.7


def test_waiting_for_post_value_when_no_post_obs():
    events = _cycle_base(old_weights=False)
    observations = [_obs(datetime(2026, 7, 29, 8, 0), 18.3, run=1)]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.pre_weight_lbs == 18.3
    assert resolved.post_weight_lbs is None
    assert resolved.post_resolution_status == STATUS_WAITING_FOR_POST_VALUE


def test_repair_classifier_buckets():
    assert (
        classify_post_repair(
            current_post=23.5,
            proposed_post=21.5,
            post_status=STATUS_CONFIRMED,
            manual_locked=False,
            completion_event_would_change=False,
            event_chain_complete=True,
            post_event_deterministic=True,
        )
        == "safe_automatic_correction"
    )
    # Confirmed but incomplete chain → not automatic
    assert (
        classify_post_repair(
            current_post=23.5,
            proposed_post=21.5,
            post_status=STATUS_CONFIRMED,
            manual_locked=False,
            completion_event_would_change=False,
            event_chain_complete=False,
            post_event_deterministic=True,
        )
        == "insufficient_evidence"
    )
    assert (
        classify_post_repair(
            current_post=23.5,
            proposed_post=21.5,
            post_status=STATUS_PROVISIONAL,
            manual_locked=False,
            completion_event_would_change=False,
            event_chain_complete=True,
            post_event_deterministic=True,
        )
        == "insufficient_evidence"
    )
    assert (
        classify_post_repair(
            current_post=4.8,
            proposed_post=10.8,
            post_status=STATUS_MANUAL_CORRECTION,
            manual_locked=True,
            completion_event_would_change=False,
        )
        == "manual_protected"
    )


def test_delayed_but_eventually_correct_pattern():
    """Anonymized 4I1PQDBP5R pattern."""
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 7, 0), None, run=0),  # invalid skipped
        _obs(datetime(2026, 7, 29, 11, 30), 18.3, run=1),
        _obs(datetime(2026, 7, 29, 15, 10), 11.7, run=2),
        _obs(datetime(2026, 7, 29, 16, 10), 11.7, run=3),
    ]
    # Filter None lbs like production loader.
    observations = [o for o in observations if o["weight_num"] is not None]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.pre_weight_lbs == 18.3
    assert resolved.post_weight_lbs == 11.7
    assert resolved.post_resolution_status == STATUS_CONFIRMED


def test_three_hours_alone_does_not_confirm_equal_pre():
    """Elapsed time is non-authoritative — one late PRE-equal obs stays provisional."""
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 23.5, run=1),
        # POST event at 10:05; single observation 4h later still equals PRE
        _obs(datetime(2026, 7, 29, 14, 10), 23.5, run=2),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.post_weight_lbs == 23.5
    assert resolved.post_resolution_status == STATUS_PROVISIONAL


def test_duplicate_same_run_rows_do_not_count_as_consecutive():
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 12.5, run=1, row_id=1),
        # Two DB rows from the same scrape/run after POST — must not confirm equal.
        _obs(datetime(2026, 7, 29, 10, 30), 12.5, run=2, row_id=10),
        _obs(datetime(2026, 7, 29, 10, 30), 12.5, run=2, row_id=11),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.post_resolution_status == STATUS_PROVISIONAL


def test_two_distinct_runs_equal_pre_confirms_equal():
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 12.5, run=1),
        _obs(datetime(2026, 7, 29, 10, 30), 12.5, run=2),
        _obs(datetime(2026, 7, 29, 11, 30), 12.5, run=3),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.post_resolution_status == STATUS_EQUAL_VALUES_CONFIRMED


def test_conflicting_later_observations():
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 23.5, run=1),
        _obs(datetime(2026, 7, 29, 10, 30), 23.5, run=2),
        _obs(datetime(2026, 7, 29, 12, 0), 21.5, run=3),
        _obs(datetime(2026, 7, 29, 13, 0), 20.0, run=4),  # conflict, no consecutive pair
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.post_resolution_status == STATUS_CONFLICTING_OBSERVATIONS


def test_confirmed_post_not_rewritten_by_single_later_scrape():
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 23.5, run=1),
        _obs(datetime(2026, 7, 29, 10, 30), 21.5, run=2),
        _obs(datetime(2026, 7, 29, 11, 30), 21.5, run=3),  # confirmed 21.5
        _obs(datetime(2026, 7, 29, 14, 0), 20.0, run=4),  # single later — must not win
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.post_weight_lbs == 21.5
    assert resolved.post_resolution_status == STATUS_CONFIRMED


def test_confirmed_post_superseded_only_by_two_consecutive_new_value():
    events = _cycle_base(old_weights=False)
    observations = [
        _obs(datetime(2026, 7, 29, 8, 0), 23.5, run=1),
        _obs(datetime(2026, 7, 29, 10, 30), 21.5, run=2),
        _obs(datetime(2026, 7, 29, 11, 30), 21.5, run=3),
        _obs(datetime(2026, 7, 29, 14, 0), 20.0, run=4),
        _obs(datetime(2026, 7, 29, 15, 0), 20.0, run=5),  # stronger rule
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.post_weight_lbs == 20.0
    assert resolved.post_resolution_status == STATUS_CONFIRMED


def test_pre_uses_latest_pre_review_event_only_for_observation_window():
    """Earlier pre-review weigh is ignored; obs before latest PRE do not attach."""
    events = [
        _ev("sent-to-vendor", datetime(2026, 7, 29, 5, 0), eid=1),
        _ev("move-bag", datetime(2026, 7, 29, 5, 30), eid=2, rack="VeeWash Dirty"),
        _ev("weight-entry", datetime(2026, 7, 29, 6, 0), eid=3, user="FirstPre"),
        _ev("weight-entry", datetime(2026, 7, 29, 7, 0), eid=4, user="LatestPre"),
        _ev("garments-reviewed", datetime(2026, 7, 29, 10, 0), eid=5),
        _ev("weight-entry", datetime(2026, 7, 29, 10, 5), eid=6, user="Post"),
    ]
    observations = [
        # Between first and latest PRE — must NOT populate selected PRE.
        _obs(datetime(2026, 7, 29, 6, 30), 99.0, run=1),
        # After latest PRE — attaches to selected PRE.
        _obs(datetime(2026, 7, 29, 7, 30), 18.0, run=2),
        _obs(datetime(2026, 7, 29, 11, 0), 11.0, run=3),
        _obs(datetime(2026, 7, 29, 12, 0), 11.0, run=4),
    ]
    resolved = resolve_current_cycle_weights(
        events, selected_date_et=DAY, observations=observations
    )
    assert resolved.pre_weight_event_id == 4
    assert resolved.pre_weight_lbs == 18.0
    assert resolved.pre_weight_lbs != 99.0
    assert resolved.post_weight_lbs == 11.0


def test_attach_reconcile_allows_provisional_but_not_confirmed_or_manual():
    from backend.rinse_scan_weight_enrichment import (
        WEIGHT_ROLE_POST,
        attach_observations_to_weight_events,
    )

    class _Cur:
        def __init__(self):
            self.scan_events = []
            self.rowcount = 0
            self._result = []

        def execute(self, sql, params=None):
            s = " ".join(str(sql).split()).lower()
            if "information_schema" in s or "show tables" in s:
                self._result = [{"c": 1}]
                return
            if s.startswith("update rinse_bag_scan_events"):
                # emulate overwrite path
                self.rowcount = 1
                for ev in self.scan_events:
                    if ev.get("id") == params[-3] or ev.get("id") == params[8]:
                        # params layout varies; match by id in params
                        pass
                sid = None
                for p in params:
                    if isinstance(p, int) and p in {2}:
                        sid = p
                # Find id near end
                for p in reversed(list(params)):
                    if isinstance(p, int) and any(e.get("id") == p for e in self.scan_events):
                        sid = p
                        break
                for ev in self.scan_events:
                    if ev.get("id") == sid:
                        ev["weight_lbs"] = params[0]
                        ev["weight_role"] = params[7] if len(params) > 7 else "POST"
                self._result = []
                return
            if "from rinse_bag_scan_events" in s and "select" in s:
                self._result = list(self.scan_events)
                return
            if "rinse_step1" in s:
                self._result = []
                return
            self._result = []

        def fetchall(self):
            return list(self._result)

        def fetchone(self):
            return self._result[0] if self._result else None

    # Use real attach with events passed in (skips DB load for events)
    events = [
        {
            "id": 1,
            "purpose": "weight-entry",
            "scanned_at_parsed": datetime(2026, 7, 29, 6, 0),
            "weight_lbs": 23.5,
            "weight_role": "PRE",
            "user_name": "A",
        },
        {
            "id": 2,
            "purpose": "weight-entry",
            "scanned_at_parsed": datetime(2026, 7, 29, 10, 0),
            "weight_lbs": 23.5,  # provisional (= PRE)
            "weight_role": "POST",
            "user_name": "B",
        },
    ]
    cur = _Cur()
    cur.scan_events = list(events)
    obs = [
        {"weight_num": 21.5, "observed_at": datetime(2026, 7, 29, 12, 0), "presence_run_id": 9}
    ]
    result = attach_observations_to_weight_events(
        cur, 3, "BAG1", observations=obs, events=events, dry_run=True
    )
    assert result["updated_count"] == 1
    assert result["attached"][0]["reconciled"] is True
    assert result["attached"][0]["weight_lbs"] == 21.5

    # Confirmed POST (differs from PRE) must not reconcile on ordinary obs
    events2 = [
        dict(events[0]),
        {
            "id": 2,
            "purpose": "weight-entry",
            "scanned_at_parsed": datetime(2026, 7, 29, 10, 0),
            "weight_lbs": 21.5,  # already confirmed-ish (≠ PRE)
            "weight_role": "POST",
            "weight_source": "portal_weight_num",
            "user_name": "B",
        },
    ]
    result2 = attach_observations_to_weight_events(
        cur,
        3,
        "BAG1",
        observations=[{"weight_num": 20.0, "observed_at": datetime(2026, 7, 29, 13, 0), "presence_run_id": 10}],
        events=events2,
        dry_run=True,
    )
    assert result2["updated_count"] == 0


def test_pre_fallback_without_configured_rack_entry_single_weight():
    """Anchor exists, ENTRY_NOT_FOUND — still project factual PRE for display."""
    day = date(2026, 8, 8)
    events = [
        _ev("sent-to-vendor", datetime(2026, 8, 8, 14, 22), eid=1, rack=None),
        _ev(
            "weight-entry",
            datetime(2026, 8, 8, 15, 7),
            eid=2,
            lbs=22.8,
            user="Sarah Kamran",
            weight_role="PRE",
        ),
    ]
    selected = select_current_cycle_weight_events(events, selected_date_et=day)
    assert selected["entry_at"] is None
    assert selected["cycle"].entry_at is None
    assert selected["pre_event"]["id"] == 2
    assert selected["post_event"] is None

    resolved = resolve_current_cycle_weights(events, selected_date_et=day)
    assert resolved.entry_at is None
    assert resolved.pre_weight_lbs == 22.8
    assert resolved.pre_weight_event_id == 2
    assert resolved.pre_weight_event_at == datetime(2026, 8, 8, 15, 7)
    assert resolved.post_weight_lbs is None
    assert resolved.post_weight_event_id is None
    assert resolved.weight_entry_count == 1


def test_pre_fallback_prefers_weight_role_pre_not_later_same_lbs():
    """4QKX443PML shape: PRE role at 3:07; later same-lbs weight is not PRE."""
    day = date(2026, 8, 8)
    events = [
        _ev("sent-to-vendor", datetime(2026, 8, 8, 14, 22), eid=1943716, rack=None),
        _ev(
            "weight-entry",
            datetime(2026, 8, 8, 15, 7),
            eid=1943714,
            lbs=22.8,
            user="Sarah Kamran",
            weight_role="PRE",
        ),
        _ev("garments-reviewed", datetime(2026, 8, 8, 16, 36), eid=1944079),
        _ev(
            "weight-entry",
            datetime(2026, 8, 8, 16, 38),
            eid=1944075,
            lbs=22.8,
            user="Maria (Veewash)",
        ),
    ]
    selected = select_current_cycle_weight_events(events, selected_date_et=day)
    assert selected["entry_at"] is None
    assert selected["cycle"].entry_at is None
    # Live bag reports ENTRY_NOT_FOUND; keep entry unresolved either way.
    assert selected["cycle"].pending_reason in (None, "ENTRY_NOT_FOUND")
    assert selected["pre_event"]["id"] == 1943714
    # Fallback must not invent POST / completion evidence.
    assert selected["post_event"] is None
    assert selected["garments_reviewed_at"] is None

    resolved = resolve_current_cycle_weights(events, selected_date_et=day)
    assert resolved.entry_at is None
    assert resolved.pre_weight_lbs == 22.8
    assert resolved.pre_weight_event_id == 1943714
    assert resolved.pre_weight_event_at == datetime(2026, 8, 8, 15, 7)
    assert resolved.post_weight_event_id is None
    assert resolved.post_weight_lbs is None


def test_pre_fallback_ignores_lifetime_weights_before_anchor():
    day = date(2026, 8, 8)
    events = [
        _ev("sent-to-vendor", datetime(2026, 7, 1, 8, 0), eid=1, rack="VeeWash Dirty"),
        _ev("weight-entry", datetime(2026, 7, 1, 9, 0), eid=2, lbs=99.0, weight_role="PRE"),
        _ev("sent-to-vendor", datetime(2026, 8, 8, 14, 22), eid=3, rack=None),
        _ev(
            "weight-entry",
            datetime(2026, 8, 8, 15, 7),
            eid=4,
            lbs=22.8,
            weight_role="PRE",
        ),
    ]
    selected = select_current_cycle_weight_events(events, selected_date_et=day)
    assert selected["entry_at"] is None
    assert selected["pre_event"]["id"] == 4
    resolved = resolve_current_cycle_weights(events, selected_date_et=day)
    assert resolved.pre_weight_lbs == 22.8
    assert resolved.pre_weight_lbs != 99.0


def test_pre_fallback_does_not_override_when_entry_exists():
    """Configured-rack entry path unchanged — latest pre-review still wins."""
    events = _cycle_base(old_weights=False)
    selected = select_current_cycle_weight_events(events, selected_date_et=DAY)
    assert selected["entry_at"] is not None
    assert selected["pre_event"]["id"] == 12
    assert selected["post_event"]["id"] == 14
