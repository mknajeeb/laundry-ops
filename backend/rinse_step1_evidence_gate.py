"""Durable Stage-B evidence gate keyed by scan-import batch.

Incomplete imports (``import_incomplete``, ``timeline_replacement_deferred``,
coverage incomplete, import running, invalid_for_step1_rebuild) are persisted
against the upload batch so every Stage-B path — in-cycle, watchdog, retry,
manual refresh — resolves the same batch-backed decision without relying on a
transient ``force_incomplete`` argument.

Bag-level projection deferral (e.g. ``incoming_max_older_than_existing``) is
stored in ``detail_json`` and does **not** freeze unrelated eligible bags.
Only a true global incomplete batch (no projection-eligible bags), mid-cycle
``import_running``, coverage/invalid flags, or a later complete tip supersession
rules Stage-B allow/deny.

Only a later *complete* batch may clear the org tip. Batch N incomplete stays
blocking for any Stage B that targets batch N.

``GATE_IMPORT_RUNNING`` is the mid-cycle phase stamp for active scan-events
DB write / timeline merge. It must be committed before mutation starts and
replaced with a terminal complete/incomplete state when the import function
exits (success or failure). Overall ``rinse_scrape_runs.status='running'``
is not a Stage-B blocker by itself.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Mapping

from backend.ta_helpers import table_exists

GATE_COMPLETE = "complete"
GATE_INCOMPLETE = "incomplete"
GATE_IMPORT_RUNNING = "import_running"
GATE_COVERAGE_INCOMPLETE = "coverage_incomplete"
GATE_INVALID = "invalid_for_step1_rebuild"

# Canonical Stage-B defer reason when a scan-import batch is incomplete.
REASON_IMPORT_BATCH_INCOMPLETE = "import_batch_incomplete"
REASON_IMPORT_RUNNING = "import_running"

# Stuck import_running rows older than this are treated as failed imports so
# Retry cannot remain blocked after a killed scheduler process.
def _import_running_stale_minutes() -> int:
    try:
        raw = os.getenv("RINSE_IMPORT_RUNNING_STALE_MINUTES")
        if raw is not None and str(raw).strip():
            return max(5, min(240, int(raw)))
    except (TypeError, ValueError):
        pass
    try:
        return max(5, min(240, int(os.getenv("RINSE_SCRAPE_STALE_MINUTES", "120"))))
    except (TypeError, ValueError):
        return 120

BLOCKING_STATUSES = frozenset(
    {
        GATE_INCOMPLETE,
        GATE_IMPORT_RUNNING,
        GATE_COVERAGE_INCOMPLETE,
        GATE_INVALID,
        "import_incomplete",
        REASON_IMPORT_BATCH_INCOMPLETE,
        "timeline_replacement_deferred",
        "coverage_incomplete",
        "import_running",
        "invalid_for_step1_rebuild",
    }
)


def _utcnow() -> datetime:
    return datetime.utcnow()


def ensure_step1_evidence_gate_table(cursor) -> None:
    if table_exists(cursor, "rinse_step1_evidence_gate"):
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rinse_step1_evidence_gate (
          id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
          organization_id INT NOT NULL,
          import_batch_id INT NOT NULL,
          scrape_run_id BIGINT NULL,
          portal_presence_run_id BIGINT NULL,
          evidence_generation_id VARCHAR(64) NULL,
          gate_status VARCHAR(64) NOT NULL,
          gate_reason VARCHAR(128) NULL,
          import_incomplete TINYINT(1) NOT NULL DEFAULT 0,
          timeline_replacement_deferred TINYINT(1) NOT NULL DEFAULT 0,
          coverage_incomplete TINYINT(1) NOT NULL DEFAULT 0,
          invalid_for_step1_rebuild TINYINT(1) NOT NULL DEFAULT 0,
          detail_json JSON NULL,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_step1_evidence_gate_batch (organization_id, import_batch_id),
          INDEX idx_step1_evidence_gate_org_status (organization_id, gate_status, import_batch_id),
          INDEX idx_step1_evidence_gate_scrape (scrape_run_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _json_dump(payload: Mapping[str, Any] | None) -> str | None:
    if not payload:
        return None
    try:
        return json.dumps(dict(payload), default=str)
    except (TypeError, ValueError):
        return None


def merge_flags_indicate_incomplete(merge: Mapping[str, Any] | None) -> bool:
    """True when Stage-B must globally defer (no eligible bags to project).

    Selective deferred bags alone do **not** mark the batch globally incomplete.
    """
    if not isinstance(merge, Mapping):
        return False
    if merge.get("stage_b_global_incomplete") is True:
        return True
    deferred = merge.get("bags_projection_deferred")
    eligible = merge.get("bags_projection_eligible")
    if isinstance(deferred, (list, tuple)) or isinstance(eligible, (list, tuple)):
        deferred_n = len(deferred or [])
        eligible_n = len(eligible or [])
        return deferred_n > 0 and eligible_n == 0
    return bool(
        merge.get("import_incomplete")
        or merge.get("timeline_replacement_deferred")
        or merge.get("coverage_incomplete")
        or merge.get("invalid_for_step1_rebuild")
    )


def projection_deferred_bag_ids_from_merge(
    merge: Mapping[str, Any] | None,
) -> list[str]:
    if not isinstance(merge, Mapping):
        return []
    raw = merge.get("bags_projection_deferred") or []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        bid = str(item or "").strip().upper()
        if bid and bid not in seen:
            seen.add(bid)
            out.append(bid)
    return out


def parse_evidence_gate_detail(detail_json: Any) -> dict[str, Any]:
    if isinstance(detail_json, Mapping):
        return dict(detail_json)
    if isinstance(detail_json, (bytes, bytearray)):
        detail_json = detail_json.decode("utf-8", errors="replace")
    if isinstance(detail_json, str) and detail_json.strip():
        try:
            parsed = json.loads(detail_json)
            return dict(parsed) if isinstance(parsed, Mapping) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def projection_deferred_bag_ids_from_gate_row(
    gate: Mapping[str, Any] | None,
) -> list[str]:
    if not isinstance(gate, Mapping):
        return []
    detail = parse_evidence_gate_detail(gate.get("detail_json"))
    raw = detail.get("projection_deferred_bag_ids") or detail.get(
        "bags_projection_deferred"
    ) or []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        bid = str(item or "").strip().upper()
        if bid and bid not in seen:
            seen.add(bid)
            out.append(bid)
    return out


def fetch_projection_deferred_bag_ids(
    cursor,
    organization_id: int,
    import_batch_id: int | None,
) -> list[str]:
    if import_batch_id is None:
        return []
    gate = fetch_evidence_gate(cursor, int(organization_id), int(import_batch_id))
    return projection_deferred_bag_ids_from_gate_row(gate)


def record_evidence_gate_for_batch(
    cursor,
    *,
    organization_id: int,
    import_batch_id: int,
    scrape_run_id: int | None = None,
    portal_presence_run_id: int | None = None,
    evidence_generation_id: str | None = None,
    import_incomplete: bool = False,
    timeline_replacement_deferred: bool = False,
    coverage_incomplete: bool = False,
    invalid_for_step1_rebuild: bool = False,
    import_running: bool = False,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Upsert durable gate row for a scan-import batch. Returns gate decision."""
    ensure_step1_evidence_gate_table(cursor)
    org = int(organization_id)
    batch_id = int(import_batch_id)

    blocking = bool(
        import_incomplete
        or timeline_replacement_deferred
        or coverage_incomplete
        or invalid_for_step1_rebuild
        or import_running
    )
    if import_running:
        status = GATE_IMPORT_RUNNING
        reason = "import_running"
    elif invalid_for_step1_rebuild:
        status = GATE_INVALID
        reason = "invalid_for_step1_rebuild"
    elif coverage_incomplete:
        status = GATE_COVERAGE_INCOMPLETE
        reason = "coverage_incomplete"
    elif import_incomplete or timeline_replacement_deferred:
        status = GATE_INCOMPLETE
        reason = REASON_IMPORT_BATCH_INCOMPLETE
    else:
        status = GATE_COMPLETE
        reason = None

    evidence_id = (
        str(evidence_generation_id).strip()
        if evidence_generation_id
        else f"batch:{batch_id}"
    )
    cursor.execute(
        """
        INSERT INTO rinse_step1_evidence_gate (
          organization_id, import_batch_id, scrape_run_id, portal_presence_run_id,
          evidence_generation_id, gate_status, gate_reason,
          import_incomplete, timeline_replacement_deferred, coverage_incomplete,
          invalid_for_step1_rebuild, detail_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        AS incoming
        ON DUPLICATE KEY UPDATE
          scrape_run_id = COALESCE(incoming.scrape_run_id, rinse_step1_evidence_gate.scrape_run_id),
          portal_presence_run_id = COALESCE(
            incoming.portal_presence_run_id, rinse_step1_evidence_gate.portal_presence_run_id
          ),
          evidence_generation_id = incoming.evidence_generation_id,
          gate_status = incoming.gate_status,
          gate_reason = incoming.gate_reason,
          import_incomplete = incoming.import_incomplete,
          timeline_replacement_deferred = incoming.timeline_replacement_deferred,
          coverage_incomplete = incoming.coverage_incomplete,
          invalid_for_step1_rebuild = incoming.invalid_for_step1_rebuild,
          detail_json = incoming.detail_json,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            org,
            batch_id,
            int(scrape_run_id) if scrape_run_id is not None else None,
            int(portal_presence_run_id) if portal_presence_run_id is not None else None,
            evidence_id[:64],
            status,
            reason,
            1 if import_incomplete or timeline_replacement_deferred else 0,
            1 if timeline_replacement_deferred else 0,
            1 if coverage_incomplete else 0,
            1 if invalid_for_step1_rebuild else 0,
            _json_dump(detail),
        ),
    )
    return {
        "organization_id": org,
        "import_batch_id": batch_id,
        "scrape_run_id": int(scrape_run_id) if scrape_run_id is not None else None,
        "portal_presence_run_id": (
            int(portal_presence_run_id) if portal_presence_run_id is not None else None
        ),
        "evidence_generation_id": evidence_id,
        "gate_status": status,
        "gate_reason": reason,
        "allow_persist": not blocking,
        "blocking": blocking,
        "import_incomplete": bool(import_incomplete or timeline_replacement_deferred),
        "timeline_replacement_deferred": bool(timeline_replacement_deferred),
        "coverage_incomplete": bool(coverage_incomplete),
        "invalid_for_step1_rebuild": bool(invalid_for_step1_rebuild),
        "recorded_at": _utcnow().isoformat(sep=" "),
    }


def record_evidence_gate_from_merge(
    cursor,
    *,
    organization_id: int,
    import_batch_id: int | None,
    scrape_run_id: int | None = None,
    portal_presence_run_id: int | None = None,
    merge: Mapping[str, Any] | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Record gate from a persistent_merge payload. No-op without batch id.

    Selective incomplete bags are stored in ``detail_json`` and do not block
    Stage-B for projection-eligible bags in the same batch.
    """
    if import_batch_id is None:
        return None
    incomplete = merge_flags_indicate_incomplete(merge)
    deferred_ids = projection_deferred_bag_ids_from_merge(merge)
    eligible_ids: list[str] = []
    if isinstance(merge, Mapping):
        raw_eligible = merge.get("bags_projection_eligible") or []
        if isinstance(raw_eligible, (list, tuple)):
            seen: set[str] = set()
            for item in raw_eligible:
                bid = str(item or "").strip().upper()
                if bid and bid not in seen:
                    seen.add(bid)
                    eligible_ids.append(bid)
    detail_payload: dict[str, Any] = {
        **(dict(detail) if isinstance(detail, Mapping) else {}),
        "merge_flags": {
            "import_incomplete": bool(
                isinstance(merge, Mapping) and merge.get("import_incomplete")
            ),
            "timeline_replacement_deferred": bool(
                isinstance(merge, Mapping)
                and merge.get("timeline_replacement_deferred")
            ),
            "stage_b_global_incomplete": incomplete,
            "has_projection_deferred_bags": bool(deferred_ids),
        },
        "projection_deferred_bag_ids": deferred_ids,
        "projection_eligible_bag_ids": eligible_ids,
        "projection_eligible_count": len(eligible_ids),
        "projection_deferred_count": len(deferred_ids),
    }
    if isinstance(merge, Mapping) and merge.get("bags_projection_deferred_reasons"):
        detail_payload["bags_projection_deferred_reasons"] = merge.get(
            "bags_projection_deferred_reasons"
        )
    return record_evidence_gate_for_batch(
        cursor,
        organization_id=organization_id,
        import_batch_id=int(import_batch_id),
        scrape_run_id=scrape_run_id,
        portal_presence_run_id=portal_presence_run_id,
        import_incomplete=incomplete,
        timeline_replacement_deferred=incomplete,
        coverage_incomplete=bool(
            isinstance(merge, Mapping) and merge.get("coverage_incomplete")
        ),
        invalid_for_step1_rebuild=bool(
            isinstance(merge, Mapping) and merge.get("invalid_for_step1_rebuild")
        ),
        detail=detail_payload,
    )


def record_scan_import_running(
    cursor,
    *,
    organization_id: int,
    import_batch_id: int,
    scrape_run_id: int | None = None,
    portal_presence_run_id: int | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Mark scan chronology mutation in progress (must be committed before mutate)."""
    payload = {
        "phase": GATE_IMPORT_RUNNING,
        "started_at": _utcnow().isoformat(sep=" "),
        **(dict(detail) if isinstance(detail, Mapping) else {}),
    }
    return record_evidence_gate_for_batch(
        cursor,
        organization_id=organization_id,
        import_batch_id=int(import_batch_id),
        scrape_run_id=scrape_run_id,
        portal_presence_run_id=portal_presence_run_id,
        import_running=True,
        detail=payload,
    )


def record_scan_import_terminal_failure(
    cursor,
    *,
    organization_id: int,
    import_batch_id: int,
    scrape_run_id: int | None = None,
    error: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Clear import_running after a failed mutation; leave a blocking incomplete tip."""
    payload = {
        "phase": "scan_import_failed",
        "finished_at": _utcnow().isoformat(sep=" "),
        "error": (error or "")[:2000] or None,
        **(dict(detail) if isinstance(detail, Mapping) else {}),
    }
    return record_evidence_gate_for_batch(
        cursor,
        organization_id=organization_id,
        import_batch_id=int(import_batch_id),
        scrape_run_id=scrape_run_id,
        import_incomplete=True,
        detail=payload,
    )


def reconcile_stale_import_running_gates(cursor, organization_id: int) -> int:
    """Convert abandoned import_running rows to incomplete so Retry cannot stick."""
    if not table_exists(cursor, "rinse_step1_evidence_gate"):
        return 0
    cutoff = _utcnow() - timedelta(minutes=_import_running_stale_minutes())
    cursor.execute(
        """
        SELECT import_batch_id, scrape_run_id
        FROM rinse_step1_evidence_gate
        WHERE organization_id = %s
          AND gate_status = %s
          AND updated_at < %s
        """,
        (int(organization_id), GATE_IMPORT_RUNNING, cutoff),
    )
    rows = [r for r in (cursor.fetchall() or []) if isinstance(r, Mapping)]
    cleared = 0
    for row in rows:
        bid = row.get("import_batch_id")
        if bid is None:
            continue
        record_scan_import_terminal_failure(
            cursor,
            organization_id=organization_id,
            import_batch_id=int(bid),
            scrape_run_id=(
                int(row["scrape_run_id"]) if row.get("scrape_run_id") is not None else None
            ),
            error=(
                f"import_running gate stale after {_import_running_stale_minutes()} minutes"
            ),
            detail={"stale_reconciled": True},
        )
        cleared += 1
    return cleared


def terminalize_import_running_gates_for_scrape_runs(
    cursor,
    *,
    organization_id: int,
    scrape_run_ids: list[int],
    error: str | None = None,
) -> int:
    """Clear import_running gates for dead scrape runs (lock already proven free)."""
    if not scrape_run_ids or not table_exists(cursor, "rinse_step1_evidence_gate"):
        return 0
    ids = [int(x) for x in scrape_run_ids if x]
    if not ids:
        return 0
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT import_batch_id, scrape_run_id
        FROM rinse_step1_evidence_gate
        WHERE organization_id = %s
          AND gate_status = %s
          AND scrape_run_id IN ({placeholders})
        """,
        (int(organization_id), GATE_IMPORT_RUNNING, *ids),
    )
    cleared = 0
    for row in cursor.fetchall() or []:
        if not isinstance(row, Mapping):
            continue
        bid = row.get("import_batch_id")
        if bid is None:
            continue
        record_scan_import_terminal_failure(
            cursor,
            organization_id=organization_id,
            import_batch_id=int(bid),
            scrape_run_id=(
                int(row["scrape_run_id"]) if row.get("scrape_run_id") is not None else None
            ),
            error=error or "import_running gate cleared because scrape lock was free",
            detail={"dead_execution_reclaimed": True},
        )
        cleared += 1
    return cleared


def active_scan_import_running(
    cursor,
    organization_id: int,
    *,
    exclude_scrape_run_id: int | None = None,
) -> bool:
    """True when a non-stale import_running evidence gate exists for the org."""
    if not table_exists(cursor, "rinse_step1_evidence_gate"):
        return False
    reconcile_stale_import_running_gates(cursor, organization_id)
    cutoff = _utcnow() - timedelta(minutes=_import_running_stale_minutes())
    cursor.execute(
        """
        SELECT import_batch_id, scrape_run_id, gate_status, updated_at
        FROM rinse_step1_evidence_gate
        WHERE organization_id = %s
          AND gate_status = %s
          AND updated_at >= %s
        ORDER BY updated_at DESC, import_batch_id DESC
        LIMIT 4
        """,
        (int(organization_id), GATE_IMPORT_RUNNING, cutoff),
    )
    exclude = int(exclude_scrape_run_id) if exclude_scrape_run_id is not None else None
    for row in cursor.fetchall() or []:
        if not isinstance(row, Mapping):
            continue
        sid = row.get("scrape_run_id")
        if exclude is not None and sid is not None and int(sid) == exclude:
            continue
        return True
    return False


def fetch_evidence_gate(
    cursor,
    organization_id: int,
    import_batch_id: int,
) -> dict[str, Any] | None:
    if not table_exists(cursor, "rinse_step1_evidence_gate"):
        return None
    cursor.execute(
        """
        SELECT organization_id, import_batch_id, scrape_run_id, portal_presence_run_id,
               evidence_generation_id, gate_status, gate_reason,
               import_incomplete, timeline_replacement_deferred, coverage_incomplete,
               invalid_for_step1_rebuild, detail_json, created_at, updated_at
        FROM rinse_step1_evidence_gate
        WHERE organization_id = %s AND import_batch_id = %s
        LIMIT 1
        """,
        (int(organization_id), int(import_batch_id)),
    )
    row = cursor.fetchone()
    return dict(row) if isinstance(row, Mapping) else None


def _gate_is_blocking(row: Mapping[str, Any] | None) -> bool:
    if not row:
        return False
    status = str(row.get("gate_status") or "").strip().lower()
    if status in BLOCKING_STATUSES:
        return True
    if status == GATE_COMPLETE:
        return False
    return bool(
        row.get("import_incomplete")
        or row.get("timeline_replacement_deferred")
        or row.get("coverage_incomplete")
        or row.get("invalid_for_step1_rebuild")
    )


def resolve_batch_id_for_stage_b(
    cursor,
    organization_id: int,
    *,
    import_batch_id: int | None = None,
    scrape_run_id: int | None = None,
) -> int | None:
    """Resolve the evidence batch Stage B is evaluating."""
    if import_batch_id is not None:
        try:
            return int(import_batch_id)
        except (TypeError, ValueError):
            pass
    org = int(organization_id)
    if scrape_run_id is not None and table_exists(cursor, "rinse_scrape_runs"):
        cursor.execute(
            """
            SELECT imported_batch_id
            FROM rinse_scrape_runs
            WHERE organization_id = %s AND id = %s
            LIMIT 1
            """,
            (org, int(scrape_run_id)),
        )
        row = cursor.fetchone() or {}
        bid = row.get("imported_batch_id") if isinstance(row, Mapping) else None
        if bid is not None:
            return int(bid)
    # Prefer latest incomplete gate so null scrape_run_id cannot bypass it.
    if table_exists(cursor, "rinse_step1_evidence_gate"):
        cursor.execute(
            """
            SELECT import_batch_id, gate_status
            FROM rinse_step1_evidence_gate
            WHERE organization_id = %s
            ORDER BY import_batch_id DESC
            LIMIT 8
            """,
            (org,),
        )
        rows = cursor.fetchall() or []
        incomplete_batch: int | None = None
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            bid = row.get("import_batch_id")
            if bid is None:
                continue
            if _gate_is_blocking(row):
                incomplete_batch = int(bid)
                break
            # First (highest) complete batch: Stage B may target it.
            if str(row.get("gate_status") or "").lower() == GATE_COMPLETE:
                return int(bid)
        if incomplete_batch is not None:
            return incomplete_batch
    if table_exists(cursor, "rinse_scrape_runs"):
        cursor.execute(
            """
            SELECT imported_batch_id
            FROM rinse_scrape_runs
            WHERE organization_id = %s
              AND status IN ('success', 'needs_attention', 'partial_success')
              AND imported_batch_id IS NOT NULL
            ORDER BY finished_at DESC, id DESC
            LIMIT 1
            """,
            (org,),
        )
        row = cursor.fetchone() or {}
        bid = row.get("imported_batch_id") if isinstance(row, Mapping) else None
        if bid is not None:
            return int(bid)
    return None


def evaluate_durable_evidence_gate(
    cursor,
    organization_id: int,
    *,
    import_batch_id: int | None = None,
    scrape_run_id: int | None = None,
) -> dict[str, Any]:
    """
    Resolve batch-backed Stage-B gate.

    Incomplete batch N always blocks Stage B for that batch. A later complete
    batch N+1 is allowed. When no batch can be resolved, do not invent a block
    from this durable table alone (other chronology gates still apply).
    """
    org = int(organization_id)
    resolved_batch = resolve_batch_id_for_stage_b(
        cursor,
        org,
        import_batch_id=import_batch_id,
        scrape_run_id=scrape_run_id,
    )
    out: dict[str, Any] = {
        "organization_id": org,
        "import_batch_id": resolved_batch,
        "scrape_run_id": int(scrape_run_id) if scrape_run_id is not None else None,
        "portal_presence_run_id": None,
        "evidence_generation_id": None,
        "gate_status": None,
        "gate_reason": None,
        "allow_persist": True,
        "blocking": False,
        "durable_gate_checked": True,
        "projection_deferred_bag_ids": [],
    }
    if resolved_batch is None:
        out["durable_gate_checked"] = False
        return out

    gate = fetch_evidence_gate(cursor, org, resolved_batch)
    if not gate:
        # No durable row yet — caller may still pass force_incomplete for this cycle.
        out["gate_status"] = None
        out["gate_reason"] = "no_durable_gate_row"
        return out

    out["portal_presence_run_id"] = gate.get("portal_presence_run_id")
    out["evidence_generation_id"] = gate.get("evidence_generation_id")
    out["scrape_run_id"] = gate.get("scrape_run_id") or out["scrape_run_id"]
    out["gate_status"] = gate.get("gate_status")
    out["gate_reason"] = gate.get("gate_reason")
    out["projection_deferred_bag_ids"] = projection_deferred_bag_ids_from_gate_row(gate)
    blocking = _gate_is_blocking(gate)
    # Later complete batch supersedes earlier incomplete when Stage B resolved
    # to that complete batch. If we resolved to an incomplete batch, block.
    if not blocking and str(gate.get("gate_status") or "").lower() == GATE_COMPLETE:
        out["allow_persist"] = True
        out["blocking"] = False
        return out
    if blocking:
        out["allow_persist"] = False
        out["blocking"] = True
        out["gate_reason"] = out["gate_reason"] or REASON_IMPORT_BATCH_INCOMPLETE
    return out
