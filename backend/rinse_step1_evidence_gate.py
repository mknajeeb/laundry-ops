"""Durable Stage-B evidence gate keyed by scan-import batch.

Incomplete imports (``import_incomplete``, ``timeline_replacement_deferred``,
coverage incomplete, import running, invalid_for_step1_rebuild) are persisted
against the upload batch so every Stage-B path — in-cycle, watchdog, retry,
manual refresh — resolves the same batch-backed decision without relying on a
transient ``force_incomplete`` argument.

Only a later *complete* batch may clear the org tip. Batch N incomplete stays
blocking for any Stage B that targets batch N.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from backend.ta_helpers import table_exists

GATE_COMPLETE = "complete"
GATE_INCOMPLETE = "incomplete"
GATE_IMPORT_RUNNING = "import_running"
GATE_COVERAGE_INCOMPLETE = "coverage_incomplete"
GATE_INVALID = "invalid_for_step1_rebuild"

# Canonical Stage-B defer reason when a scan-import batch is incomplete.
REASON_IMPORT_BATCH_INCOMPLETE = "import_batch_incomplete"

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
    if not isinstance(merge, Mapping):
        return False
    return bool(
        merge.get("import_incomplete")
        or merge.get("timeline_replacement_deferred")
        or merge.get("coverage_incomplete")
        or merge.get("invalid_for_step1_rebuild")
    )


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
    """Record gate from a persistent_merge payload. No-op without batch id."""
    if import_batch_id is None:
        return None
    incomplete = merge_flags_indicate_incomplete(merge)
    return record_evidence_gate_for_batch(
        cursor,
        organization_id=organization_id,
        import_batch_id=int(import_batch_id),
        scrape_run_id=scrape_run_id,
        portal_presence_run_id=portal_presence_run_id,
        import_incomplete=incomplete,
        timeline_replacement_deferred=bool(
            isinstance(merge, Mapping) and merge.get("timeline_replacement_deferred")
        ),
        coverage_incomplete=bool(
            isinstance(merge, Mapping) and merge.get("coverage_incomplete")
        ),
        invalid_for_step1_rebuild=bool(
            isinstance(merge, Mapping) and merge.get("invalid_for_step1_rebuild")
        ),
        detail={
            **(dict(detail) if isinstance(detail, Mapping) else {}),
            "merge_flags": {
                "import_incomplete": bool(
                    isinstance(merge, Mapping) and merge.get("import_incomplete")
                ),
                "timeline_replacement_deferred": bool(
                    isinstance(merge, Mapping)
                    and merge.get("timeline_replacement_deferred")
                ),
            },
        },
    )


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
