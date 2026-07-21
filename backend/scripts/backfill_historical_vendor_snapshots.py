"""One-time historical backfill: freeze vendor snapshots onto finalized temp/1099 lines.

PURPOSE (one-time / historical)
    Contractor receipts finalized *before* the vendor-receipt feature shipped have
    no stored vendor snapshot, so their receipts resolve the vendor live at render
    time and can therefore drift if a vendor record or worker default later changes.
    This one-time backfill freezes the same immutable snapshot the finalization
    process writes, bringing historical receipts up to the same immutability
    standard as newly finalized batches. It is safe to re-run (idempotent).

VENDOR RESOLUTION ORDER (identical to production `resolve_line_vendor`)
    line override (payout_batch_lines.vendor_id)
      -> worker default (payroll_profiles.default_vendor_id)
      -> organization default (seeded "Washmate Inc")

WHAT IT CHANGES
    Only the missing `vendor` key of a line's payout_details_json is added, using
    the exact same snapshot shape as finalize ({id, name, address, logo_url}). Every
    other stored field is preserved byte-for-byte. It does NOT modify payroll
    amounts, gross, net, taxes, YTD, payment dates, official pay dates, or any other
    payout data. An existing snapshot is never overwritten.

SCOPE (a line is eligible only if ALL hold)
    * its batch is finalized (payout_details_finalized_at IS NOT NULL);
    * document type is vendor receipt (worker_category in temp / contractor_1099);
    * no vendor snapshot currently exists on the line.

AUDIT
    One `vendor_snapshot_backfilled` event per line is appended to the batch's
    payout_details_audit_json (batch-level trail), carrying line id, batch id,
    vendor id, timestamp and actor (system migration).

SAFETY / EXIT CODES
    Defaults to a dry run; `--apply` is required to write. After `--apply` (and in
    `--verify`) the script confirms every finalized temp/1099 line resolves from a
    stored snapshot and exits nonzero if any line still resolves live. Database
    connection details come solely from the environment via backend.db / .env — no
    credentials or environment values are embedded here.

USAGE
    # dry run (default; no writes)
    python -m backend.scripts.backfill_historical_vendor_snapshots --org 3
    # apply (persists, then auto-verifies)
    python -m backend.scripts.backfill_historical_vendor_snapshots --org 3 --apply
    # verify only (exits nonzero if any receipt still resolves live)
    python -m backend.scripts.backfill_historical_vendor_snapshots --org 3 --verify
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(".env")

from backend.db import get_db
from backend.payroll_vendors import (
    ensure_payroll_vendor_tables,
    resolve_line_vendor,
    vendor_snapshot_for_finalize,
)

VENDOR_CATEGORIES = ("temp", "contractor_1099")
SYSTEM_ACTOR_ID = 0  # system migration (no interactive user)
SYSTEM_ACTOR_LABEL = "system_migration"
AUDIT_EVENT = "vendor_snapshot_backfilled"
AUDIT_REASON = "One-time backfill to freeze historical contractor receipt vendor branding"


def _fetch_finalized_vendor_lines(conn, organization_id: int) -> list[dict]:
    c = conn.cursor(dictionary=True)
    c.execute(
        """
        SELECT pbl.id, pbl.batch_id, pbl.user_id, pbl.vendor_id,
               pbl.payout_details_json,
               pb.worker_category, pb.payout_details_audit_json
        FROM payout_batch_lines pbl
        JOIN payout_batches pb ON pb.id = pbl.batch_id
        WHERE pb.organization_id = %s
          AND pb.worker_category IN ('temp', 'contractor_1099')
          AND pb.payout_details_finalized_at IS NOT NULL
        ORDER BY pbl.batch_id, pbl.id
        """,
        (int(organization_id),),
    )
    return c.fetchall() or []


def _raw_details(raw) -> dict:
    """The line's payout_details_json as the exact stored object (no normalization).

    We only ever *add* the `vendor` key to this, so every other stored field is
    preserved byte-for-byte on write.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        obj = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _has_snapshot(details: dict) -> bool:
    v = details.get("vendor")
    return isinstance(v, dict) and bool(v.get("name"))


def _audit_entry(line_id: int, batch_id: int, vendor_id) -> dict:
    return {
        "event": AUDIT_EVENT,
        "actor_id": SYSTEM_ACTOR_ID,
        "actor": SYSTEM_ACTOR_LABEL,
        "at": datetime.utcnow().isoformat(timespec="seconds"),
        "line_id": int(line_id),
        "batch_id": int(batch_id),
        "vendor_id": (int(vendor_id) if vendor_id is not None else None),
        "reason": AUDIT_REASON,
    }


def run(organization_id: int, apply: bool) -> dict:
    conn = get_db()
    ensure_payroll_vendor_tables(conn.cursor())
    rows = _fetch_finalized_vendor_lines(conn, organization_id)

    examined = len(rows)
    already = 0
    planned: list[dict] = []          # {line_id, batch_id, vendor, merged_json}
    skipped_no_vendor: list[int] = []
    # audit events + existing audit blob, grouped per batch
    batch_audit: dict[int, dict] = {}

    for r in rows:
        line_id = int(r["id"])
        batch_id = int(r["batch_id"])
        details = _raw_details(r["payout_details_json"])
        if _has_snapshot(details):
            already += 1
            continue
        line = {
            "id": line_id,
            "user_id": r.get("user_id"),
            "vendor_id": r.get("vendor_id"),
            "worker_category": r.get("worker_category"),
            "payout_details": details,
        }
        batch = {"worker_category": r.get("worker_category")}
        vendor = resolve_line_vendor(conn, int(organization_id), line, batch)
        snapshot = vendor_snapshot_for_finalize(vendor)
        if not snapshot:
            skipped_no_vendor.append(line_id)
            continue
        # Surgical: preserve every existing stored field, add only `vendor`.
        merged = dict(details)
        merged["vendor"] = snapshot
        planned.append(
            {
                "line_id": line_id,
                "batch_id": batch_id,
                "vendor": snapshot,
                "merged_json": json.dumps(merged),
            }
        )
        if batch_id not in batch_audit:
            existing = {}
            raw = r.get("payout_details_audit_json")
            if raw:
                try:
                    existing = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
                except Exception:
                    existing = {}
            events = existing.get("events") if isinstance(existing.get("events"), list) else []
            batch_audit[batch_id] = {"events": list(events)}
        batch_audit[batch_id]["events"].append(
            _audit_entry(line_id, batch_id, snapshot.get("id"))
        )

    print(f"Organization             : {organization_id}")
    print(f"Lines examined           : {examined}")
    print(f"Lines already snapshotted: {already}")
    print(f"Lines to update          : {len(planned)}")
    if skipped_no_vendor:
        print(f"Lines skipped (no vendor): {len(skipped_no_vendor)} -> {skipped_no_vendor}")
    for p in planned:
        v = p["vendor"]
        print(
            f"  line {p['line_id']} (batch {p['batch_id']}) -> vendor "
            f"id={v.get('id')} name={v.get('name')!r}"
        )

    audit_written = 0
    updated = 0
    if apply and planned:
        upd = conn.cursor()
        for p in planned:
            upd.execute(
                """
                UPDATE payout_batch_lines
                   SET payout_details_json=%s, updated_at=CURRENT_TIMESTAMP
                 WHERE id=%s AND batch_id=%s AND organization_id=%s
                """,
                (p["merged_json"], p["line_id"], p["batch_id"], int(organization_id)),
            )
            updated += upd.rowcount
        for batch_id, blob in batch_audit.items():
            audit_written += sum(
                1 for e in blob["events"] if e.get("event") == AUDIT_EVENT
            )
            upd.execute(
                """
                UPDATE payout_batches
                   SET payout_details_audit_json=%s, updated_at=CURRENT_TIMESTAMP
                 WHERE id=%s AND organization_id=%s
                """,
                (json.dumps(blob), batch_id, int(organization_id)),
            )
        conn.commit()
        print(f"\nAPPLIED: {updated} lines updated across {len(batch_audit)} batches.")
        print(f"Audit events written ({AUDIT_EVENT}): {audit_written}")
    elif not apply:
        print("\nDRY RUN — re-run with --apply to persist.")

    result = {
        "org": organization_id,
        "examined": examined,
        "already_snapshotted": already,
        "would_update" if not apply else "updated": len(planned) if not apply else updated,
        "skipped_no_vendor": skipped_no_vendor,
        "audit_entries_written": audit_written if apply else 0,
        "applied": bool(apply),
    }
    print(json.dumps(result, default=str))
    conn.close()
    return result


def verify(organization_id: int) -> list[int]:
    """Confirm every finalized temp/1099 line now resolves from a stored snapshot.

    Returns the list of line ids that still resolve live (empty == fully immutable).
    """
    conn = get_db()
    rows = _fetch_finalized_vendor_lines(conn, organization_id)
    total = len(rows)
    from_snapshot = 0
    live: list[int] = []
    for r in rows:
        details = _raw_details(r["payout_details_json"])
        line = {
            "id": int(r["id"]),
            "user_id": r.get("user_id"),
            "vendor_id": r.get("vendor_id"),
            "worker_category": r.get("worker_category"),
            "payout_details": details,
        }
        batch = {"worker_category": r.get("worker_category")}
        resolved = resolve_line_vendor(conn, int(organization_id), line, batch) or {}
        if resolved.get("snapshot") is True:
            from_snapshot += 1
        else:
            live.append(int(r["id"]))
    print(f"Finalized temp/1099 lines           : {total}")
    print(f"Resolving from stored snapshot       : {from_snapshot}")
    print(f"Still resolving live (should be none): {len(live)} {live}")
    print("VERIFIED: all historical contractor receipts are now immutable."
          if not live else "INCOMPLETE: some lines still resolve live.")
    conn.close()
    return live


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="explicit no-op (default behavior)")
    parser.add_argument("--verify", action="store_true", help="post-run snapshot resolution check")
    args = parser.parse_args()
    if args.verify:
        live = verify(args.org)
        sys.exit(1 if live else 0)
    applied = args.apply and not args.dry_run
    run(args.org, apply=applied)
    if applied:
        # A successful apply must leave every finalized receipt resolving from its
        # stored snapshot; fail loudly (nonzero) otherwise.
        print("\n=== post-apply verification ===")
        live = verify(args.org)
        sys.exit(1 if live else 0)


if __name__ == "__main__":
    main()
