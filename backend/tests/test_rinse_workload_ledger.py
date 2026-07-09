"""Regression tests for the immutable ET-day workload ledger.

Covers the acceptance criteria: once a bag is part of an ET day it stays counted;
the latest portal scrape may only change statuses, never shrink the day's total.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from backend.rinse_at_vendor_module import (
    AV_STATUS_COMPLETED,
    AV_STATUS_PENDING,
    MOD_AT_VENDOR_COMPLETED,
    MOD_AT_VENDOR_PENDING,
    _build_immutable_workload_ledger,
    _build_needs_verification_exception_rows,
    _is_operational_workload_row,
    _merge_operational_active_pending_rows,
    _merge_operational_completed_rows,
)
from backend.rinse_workload_ledger import (
    LEDGER_STATUS_COMPLETED,
    LEDGER_STATUS_NEEDS_VERIFICATION,
    LEDGER_STATUS_PENDING,
    LEDGER_STATUS_REJECTED,
    LEDGER_STATUS_SENT_TO_RINSE,
    LEDGER_TABLE,
    MEMBERSHIP_CARRYOVER_YESTERDAY,
    MEMBERSHIP_EXCLUDED_COMPLETED_BEFORE_DAY,
    MEMBERSHIP_HISTORICAL_BACKLOG,
    MEMBERSHIP_NEW_TODAY,
    MEMBERSHIP_RESEND_TODAY,
    REMOVAL_REASON_NEEDS_VERIFICATION,
    REMOVAL_REASON_REJECTED,
    build_membership_records,
    classify_bag_membership_tier,
    derive_ledger_status,
    load_workload_ledger,
    reconcile_active_ledger_breakout,
    reconcile_ledger_records,
    record_workload_membership,
)
from backend.ta_helpers import invalidate_schema_cache

ORG = 3
ET = date(2026, 7, 8)


def _pending_row(bag_id: str, *, on_portal: bool = True, svc: str = "WF", rush: str = "non_rush") -> dict:
    return {
        "bag_id": bag_id,
        "service_type": svc,
        "rush_bucket": rush,
        "at_vendor_status": AV_STATUS_PENDING,
        "module_tags": [MOD_AT_VENDOR_PENDING],
        "currently_on_vendor_home": on_portal,
    }


def _completed_row(bag_id: str, *, on_portal: bool = True, svc: str = "WF", rush: str = "non_rush") -> dict:
    return {
        "bag_id": bag_id,
        "service_type": svc,
        "rush_bucket": rush,
        "at_vendor_status": AV_STATUS_COMPLETED,
        "completed_during_et_day": True,
        "completion_timestamp": "2026-07-08T14:00:00",
        "module_tags": [MOD_AT_VENDOR_COMPLETED],
        "currently_on_vendor_home": on_portal,
    }


# ---------------------------------------------------------------------------
# Pure status-derivation behaviour
# ---------------------------------------------------------------------------


def test_completed_bag_off_portal_still_completed():
    """Scenario 1: bag leaves portal after completion -> still completed, still counted."""
    status = derive_ledger_status(_completed_row("A", on_portal=False))
    assert status == LEDGER_STATUS_COMPLETED


def test_pending_bag_off_portal_without_evidence_needs_verification():
    """A pending bag that merely vanished from the board needs verification."""
    status = derive_ledger_status(_pending_row("B", on_portal=False))
    assert status == LEDGER_STATUS_NEEDS_VERIFICATION


def test_pending_bag_with_dispatch_evidence_is_sent_to_rinse():
    """Scenario 2: positive dispatch evidence -> Sent to Rinse."""
    row = _pending_row("B2", on_portal=False)
    row["facility_status"] = "sent-to-rinse"
    assert derive_ledger_status(row) == LEDGER_STATUS_SENT_TO_RINSE


def test_stale_pending_removal_becomes_needs_verification():
    row = _pending_row("C", on_portal=True)
    status = derive_ledger_status(row, removal_reason=REMOVAL_REASON_NEEDS_VERIFICATION)
    assert status == LEDGER_STATUS_NEEDS_VERIFICATION


def test_rejected_removal_becomes_rejected():
    status = derive_ledger_status(
        _pending_row("D"), removal_reason=REMOVAL_REASON_REJECTED
    )
    assert status == LEDGER_STATUS_REJECTED


def test_completed_never_rejected_even_if_flagged():
    status = derive_ledger_status(
        _completed_row("E"), removal_reason=REMOVAL_REASON_REJECTED
    )
    assert status == LEDGER_STATUS_COMPLETED


# ---------------------------------------------------------------------------
# Reconciliation: immutable_total == sum of buckets
# ---------------------------------------------------------------------------


def test_reconcile_buckets_sum_to_total():
    records = build_membership_records(
        [_pending_row("A"), _completed_row("B"), _pending_row("C", on_portal=False)],
        removed={"D": REMOVAL_REASON_REJECTED, "E": REMOVAL_REASON_NEEDS_VERIFICATION},
        removed_rows={"D": _pending_row("D"), "E": _pending_row("E")},
    )
    recon = reconcile_ledger_records(records)
    assert recon["immutable_total"] == 5
    assert recon["reconciles"] is True
    assert (
        recon["pending"]
        + recon["completed"]
        + recon["sent_to_rinse"]
        + recon["needs_verification"]
        + recon["rejected"]
        == recon["immutable_total"]
    )


def test_scenario4_pending_down_completed_up_total_stable():
    """Scenario 4: pending decreases while completed increases; total stays the same."""
    read1 = build_membership_records([_pending_row("A"), _pending_row("B"), _pending_row("C")])
    read2 = build_membership_records([_pending_row("A"), _completed_row("B"), _completed_row("C")])
    r1 = reconcile_ledger_records(read1)
    r2 = reconcile_ledger_records(read2)
    assert r1["immutable_total"] == r2["immutable_total"] == 3
    assert r2["completed"] == 2 and r2["pending"] == 1


# ---------------------------------------------------------------------------
# Fake cursor: persistence + union across reads
# ---------------------------------------------------------------------------


def _date_iso(value) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


class FakeLedgerCursor:
    """Minimal in-memory emulation of the ledger table SQL used by the module."""

    def __init__(self, store: dict):
        self.store = store
        self._result: list = []
        self.rowcount = 0
        self.connection = None

    def executemany(self, sql: str, seq_of_params):
        for params in seq_of_params:
            self.execute(sql, params)

    def execute(self, sql: str, params=None):
        s = " ".join(sql.split())
        params = tuple(params or ())
        if s.startswith("CREATE TABLE"):
            self._result = []
            return
        if "INFORMATION_SCHEMA.TABLES" in s or "INFORMATION_SCHEMA.COLUMNS" in s:
            self._result = [{"ok": 1}]
            return
        if s.startswith("INSERT INTO"):
            (org, et_date, bid, workflow, rush, membership_tier, status, first_seen, last_seen,
             completed_at, sent_at, rejected_at, rej_reason, inclusion, source_json,
             snapshot_json, created, updated) = params
            key = (int(org), _date_iso(et_date), bid)
            existing = self.store.get(key)
            if existing is None:
                self.store[key] = {
                    "organization_id": int(org), "et_date": et_date, "bag_id": bid,
                    "workflow": workflow, "rush_bucket": rush,
                    "membership_tier": membership_tier,
                    "current_status": status,
                    "first_seen_at": first_seen, "last_seen_at": last_seen,
                    "completed_at": completed_at, "sent_to_rinse_at": sent_at,
                    "rejected_at": rejected_at, "rejection_reason": rej_reason,
                    "population_inclusion": inclusion, "source_batch_ids": source_json,
                    "row_snapshot": snapshot_json,
                }
                self.rowcount = 1
            else:
                existing["current_status"] = status
                existing["membership_tier"] = membership_tier
                existing["last_seen_at"] = last_seen
                if existing.get("completed_at") is None:
                    existing["completed_at"] = completed_at
                if status == LEDGER_STATUS_REJECTED and existing.get("rejected_at") is None:
                    existing["rejected_at"] = rejected_at
                elif status != LEDGER_STATUS_REJECTED:
                    existing["rejected_at"] = None
                existing["rejection_reason"] = rej_reason
                if workflow:
                    existing["workflow"] = workflow
                if snapshot_json is not None:
                    existing["row_snapshot"] = snapshot_json
                self.rowcount = 2
            self._result = []
            return
        if s.startswith("SELECT") and LEDGER_TABLE in s:
            org = int(params[0])
            et = params[1]
            self._result = [
                dict(rec)
                for (o, d, _b), rec in self.store.items()
                if o == org and d == _date_iso(et)
            ]
            return
        self._result = []

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


@pytest.fixture()
def fake_cursor(monkeypatch):
    invalidate_schema_cache()
    cur = FakeLedgerCursor({})

    # Route isolated persistence through the in-memory fake so tests never touch a
    # real database and membership accumulates across simulated dashboard reads.
    def _fake_persist(org, et_date, records, now=None):
        record_workload_membership(cur, org, et_date, list(records), now=now)
        return True

    monkeypatch.setattr(
        "backend.rinse_workload_ledger.persist_workload_membership_isolated",
        _fake_persist,
    )
    yield cur
    invalidate_schema_cache()


def _ledger(cursor, kept_rows, *, pre_filter_rows=None, off_portal_meta=None, rejected_ids=None):
    pre_filter = pre_filter_rows or kept_rows
    pre = {str(r["bag_id"]).upper(): r for r in pre_filter if r.get("bag_id")}
    for r in kept_rows:
        bid = str(r.get("bag_id") or "").upper()
        if bid:
            pre[bid] = r
    return _build_immutable_workload_ledger(
        cursor,
        ORG,
        ET,
        kept_rows=kept_rows,
        pre_filter_rows_by_bag=pre,
        off_portal_filter_meta=off_portal_meta or {},
        portal_scrape_rejected_ids=rejected_ids or set(),
    )


def test_record_and_load_round_trip(fake_cursor):
    records = build_membership_records([_pending_row("A"), _completed_row("B")])
    record_workload_membership(fake_cursor, ORG, ET, records)
    loaded = load_workload_ledger(fake_cursor, ORG, ET)
    assert set(loaded.keys()) == {"A", "B"}
    assert loaded["B"]["current_status"] == LEDGER_STATUS_COMPLETED


def test_reconcile_active_breakout_proofs():
    records = [
        {"bag_id": "A", "membership_tier": MEMBERSHIP_NEW_TODAY, "current_status": "pending"},
        {"bag_id": "B", "membership_tier": MEMBERSHIP_CARRYOVER_YESTERDAY, "current_status": "completed"},
        {"bag_id": "C", "membership_tier": MEMBERSHIP_RESEND_TODAY, "current_status": "pending"},
        {"bag_id": "D", "membership_tier": MEMBERSHIP_HISTORICAL_BACKLOG, "current_status": "needs_verification"},
        {"bag_id": "E", "membership_tier": MEMBERSHIP_EXCLUDED_COMPLETED_BEFORE_DAY, "current_status": "needs_verification"},
    ]
    out = reconcile_active_ledger_breakout(records)
    assert out["active_today_total"] == 3
    assert out["active_today_reconciles"] is True
    assert out["ledger_total"] == 5
    assert out["ledger_total_reconciles"] is True
    assert out["historical_backlog_total"] == 1
    assert out["excluded_completed_before_day"] == 1


def test_scenario3_fewer_bags_in_scrape_active_total_unchanged(fake_cursor):
    """Scenario 3: later scrape with fewer live bags keeps Active Today total."""
    universe = [_pending_row("A"), _pending_row("B"), _pending_row("C")]
    first = _ledger(fake_cursor, universe, pre_filter_rows=universe)
    assert first["ledger_block"]["active_today_total"] == 3

    second = _ledger(fake_cursor, [_pending_row("A")], pre_filter_rows=universe)
    assert second["ledger_block"]["active_today_total"] == 3


def test_scenario5_completed_leaves_portal_reinjected(fake_cursor):
    """Scenario 5: active completed bag that left population is re-injected."""
    _ledger(fake_cursor, [_pending_row("A"), _completed_row("B")])
    result = _ledger(fake_cursor, [_pending_row("A")])
    assert result["ledger_block"]["active_today_total"] == 2
    reinjected = {r["bag_id"] for r in result["reinjected_completed_rows"]}
    assert "B" in reinjected


def test_scenario7_no_removal_without_explicit_cancellation(fake_cursor):
    """Scenario 7: soft-removed bag stays in ledger as needs-verification, not excluded."""
    universe = [_pending_row("A"), _pending_row("B")]
    _ledger(fake_cursor, universe, pre_filter_rows=universe)
    result = _ledger(
        fake_cursor,
        [_pending_row("A")],
        pre_filter_rows=universe,
        rejected_ids={"B"},
    )
    assert result["ledger_block"]["active_today_total"] == 2
    assert result["ledger_block"]["excluded_rejected"] == 0


def test_scenario8_rush_totals_stable_after_leaving_portal(fake_cursor):
    """Scenario 8: rush / non-rush membership stays stable when bags leave the portal."""
    rows = [
        _pending_row("A", rush="rush"),
        _pending_row("B", rush="rush"),
        _pending_row("C", rush="non_rush"),
    ]
    _ledger(fake_cursor, rows)
    # Only one rush bag remains on the live board.
    second = _ledger(fake_cursor, [_pending_row("A", rush="rush")])
    loaded = load_workload_ledger(fake_cursor, ORG, ET)
    rush_ids = {b for b, rec in loaded.items() if rec.get("rush_bucket") == "rush"}
    assert rush_ids == {"A", "B"}
    assert second["ledger_block"]["immutable_total"] == 3


def test_scenario9_wf_hd_totals_stable_after_leaving_portal(fake_cursor):
    """Scenario 9: WF / HD membership stays stable when bags leave the portal."""
    rows = [
        _pending_row("A", svc="WF"),
        _pending_row("B", svc="HD"),
        _completed_row("C", svc="WF"),
    ]
    _ledger(fake_cursor, rows)
    _ledger(fake_cursor, [_pending_row("A", svc="WF")])
    loaded = load_workload_ledger(fake_cursor, ORG, ET)
    wf = {b for b, rec in loaded.items() if rec.get("workflow") == "WF"}
    hd = {b for b, rec in loaded.items() if rec.get("workflow") == "HD"}
    assert wf == {"A", "C"}
    assert hd == {"B"}


def test_active_pending_reinjected_from_portal_scrape_rejected(fake_cursor):
    """Active-tier pending bags rejected by portal scrape stay in operational workload."""
    universe = [
        _pending_row("A", on_portal=True),
        _pending_row("B", on_portal=False),
    ]
    pre = {r["bag_id"]: r for r in universe}
    kept = [_pending_row("A")]
    meta = {"off_portal_stale_pending_excluded": [], "portal_scrape_rejected_excluded": ["B"]}
    result = _build_immutable_workload_ledger(
        fake_cursor,
        ORG,
        ET,
        kept_rows=kept,
        pre_filter_rows_by_bag=pre,
        off_portal_filter_meta=meta,
        portal_scrape_rejected_ids={"B"},
    )
    tiers = dict(result.get("membership_tiers_by_bag") or {})
    ops = _merge_operational_active_pending_rows(
        kept,
        pre,
        active_bag_ids=result["active_bag_ids"],
        off_portal_filter_meta=meta,
        membership_tiers_by_bag=tiers,
    )
    nv = _build_needs_verification_exception_rows(
        pre,
        meta,
        active_bag_ids=result["active_bag_ids"],
        membership_tiers_by_bag=tiers,
    )
    assert {r["bag_id"] for r in ops} == {"A", "B"}
    assert len(nv) == 0


def test_operational_total_excludes_needs_verification(fake_cursor):
    """Operational dashboard: Total = Pending + Completed; NV is separate."""
    universe = [
        _pending_row("A", on_portal=True),
        _pending_row("B", on_portal=False),
        _completed_row("C", on_portal=False),
    ]
    pre = {r["bag_id"]: r for r in universe}
    kept = [_pending_row("A"), _completed_row("C")]
    result = _build_immutable_workload_ledger(
        fake_cursor,
        ORG,
        ET,
        kept_rows=kept,
        pre_filter_rows_by_bag=pre,
        off_portal_filter_meta={"off_portal_stale_pending_excluded": ["B"]},
        portal_scrape_rejected_ids=set(),
    )
    nv = _build_needs_verification_exception_rows(
        pre,
        {"off_portal_stale_pending_excluded": ["B"]},
        active_bag_ids=result.get("active_bag_ids"),
    )
    ops = [r for r in kept if _is_operational_workload_row(r)]
    ops = _merge_operational_completed_rows(ops, pre, active_bag_ids=result["active_bag_ids"])
    pending = sum(1 for r in ops if MOD_AT_VENDOR_PENDING in r.get("module_tags", []))
    completed = sum(1 for r in ops if MOD_AT_VENDOR_COMPLETED in r.get("module_tags", []))
    assert len(nv) == 1
    assert nv[0]["bag_id"] == "B"
    assert pending + completed == len(ops)
    assert "B" not in {r["bag_id"] for r in ops}


def test_historical_reload_matches_earlier_total(fake_cursor):
    """Scenario 6: reloading a historical day yields the same total as before."""
    _ledger(fake_cursor, [_pending_row("A"), _pending_row("B"), _completed_row("C")])
    before = reconcile_ledger_records(
        list(load_workload_ledger(fake_cursor, ORG, ET).values())
    )
    # Reload much later; live board is empty.
    _ledger(fake_cursor, [])
    after = reconcile_ledger_records(
        list(load_workload_ledger(fake_cursor, ORG, ET).values())
    )
    assert before["immutable_total"] == after["immutable_total"] == 3
