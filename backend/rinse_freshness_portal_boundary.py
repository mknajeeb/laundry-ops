"""Safe portal early-stop: never assume page 1 == delta.

Portal does not expose a documented “changed since T” API, and we have not proven
that page 1 is always newest-first. Early-stop is therefore fingerprint-based:

  fetch page → compare stable bag IDs + field fingerprints vs known state
  → continue while new/changed/uncertain
  → stop only after N consecutive fully-known unchanged pages
  → page budget is a latency safeguard and marks source_inspected_complete=false

A budget stop must never silently claim the source was fully inspected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable


def bag_fingerprint(row: dict[str, Any]) -> str:
    """Stable fingerprint shared with scrape.mjs early-stop (must match Node).

    Format (first 24 chars of raw string — NOT a hash):
      BAGID|customer|edd|lbs|service
    """
    bag = (
        str(row.get("bag_id") or row.get("Bag ID") or row.get("ticket_id") or "")
        .strip()
        .upper()
    )
    customer = str(
        row.get("customer")
        or row.get("Customer")
        or row.get("customer_name")
        or ""
    )
    edd = str(
        row.get("edd")
        or row.get("estimated_delivery")
        or row.get("Estd Delivery")
        or row.get("Estimated Delivery")
        or ""
    )
    lbs = str(
        row.get("lbs")
        or row.get("weight")
        or row.get("weight_lbs")
        or row.get("WF LBS")
        or ""
    )
    service = str(
        row.get("service")
        or row.get("Service")
        or row.get("service_class")
        or ""
    )
    raw = f"{bag}|{customer}|{edd}|{lbs}|{service}"
    return raw[:24]


def normalize_bag_id(row: dict[str, Any]) -> str:
    return (
        str(row.get("bag_id") or row.get("Bag ID") or row.get("ticket_id") or "")
        .strip()
        .upper()
    )


@dataclass
class EarlyStopState:
    known_fingerprints: dict[str, str] = field(default_factory=dict)
    consecutive_unchanged_pages: int = 0
    pages_scraped: int = 0
    new_or_changed_ids: set[str] = field(default_factory=set)
    unchanged_ids: set[str] = field(default_factory=set)
    uncertain_ids: set[str] = field(default_factory=set)
    stopped_reason: str | None = None
    source_inspected_complete: bool = False

    def observe_page(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        unchanged_pages_to_stop: int = 2,
        page_budget: int | None = None,
    ) -> str | None:
        """
        Ingest one portal page. Returns stop reason or None to continue.
        """
        self.pages_scraped += 1
        page_new = 0
        page_changed = 0
        page_same = 0
        page_uncertain = 0
        for row in rows:
            bid = normalize_bag_id(row)
            if not bid:
                page_uncertain += 1
                continue
            fp = bag_fingerprint(row)
            known = self.known_fingerprints.get(bid)
            if known is None:
                page_new += 1
                self.new_or_changed_ids.add(bid)
                self.known_fingerprints[bid] = fp
            elif known != fp:
                page_changed += 1
                self.new_or_changed_ids.add(bid)
                self.known_fingerprints[bid] = fp
            else:
                page_same += 1
                self.unchanged_ids.add(bid)

        if page_new or page_changed or page_uncertain:
            self.consecutive_unchanged_pages = 0
            if page_uncertain:
                # Unknown/unparseable rows force continued traversal.
                self.uncertain_ids.add(f"page:{self.pages_scraped}")
        else:
            self.consecutive_unchanged_pages += 1

        if (
            unchanged_pages_to_stop > 0
            and self.consecutive_unchanged_pages >= unchanged_pages_to_stop
            and self.pages_scraped >= unchanged_pages_to_stop
        ):
            self.stopped_reason = "safe_unchanged_boundary"
            self.source_inspected_complete = True
            return self.stopped_reason

        if page_budget is not None and self.pages_scraped >= int(page_budget):
            self.stopped_reason = "page_budget"
            # Budget is NOT a completeness claim.
            self.source_inspected_complete = False
            return self.stopped_reason

        return None

    def to_meta(self) -> dict[str, Any]:
        return {
            "early_stop_algorithm": "stable_bag_id_fingerprint_boundary",
            "pages_scraped": self.pages_scraped,
            "stopped_reason": self.stopped_reason,
            "source_inspected_complete": bool(self.source_inspected_complete),
            "new_or_changed_count": len(self.new_or_changed_ids),
            "unchanged_count": len(self.unchanged_ids),
            "uncertain_pages": len(self.uncertain_ids),
            "consecutive_unchanged_pages": self.consecutive_unchanged_pages,
            "note": (
                "Page-1-only is not assumed. Stop requires consecutive pages whose "
                "stable bag IDs all match known fingerprints, or a page budget that "
                "marks inspection incomplete for rolling/deep reconciliation."
            ),
        }


def load_known_fingerprints_from_presence(
    cursor, organization_id: int, *, limit: int = 5000
) -> dict[str, str]:
    """Best-effort fingerprints from recent presence rows (additive safety net)."""
    out: dict[str, str] = {}
    try:
        cursor.execute(
            """
            SELECT bag_id, customer_name, portal_status, estimated_delivery,
                   service_class, weight_lbs, special_instructions
            FROM rinse_cleaner_ticket_presence
            WHERE organization_id = %s
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (int(organization_id), int(limit)),
        )
    except Exception:
        return out
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            continue
        bid = normalize_bag_id(
            {"bag_id": row.get("bag_id"), "ticket_id": row.get("bag_id")}
        )
        if not bid:
            continue
        fp = bag_fingerprint(
            {
                "bag_id": bid,
                "customer": row.get("customer_name"),
                "status": row.get("portal_status"),
                "edd": row.get("estimated_delivery"),
                "service": row.get("service_class"),
                "lbs": row.get("weight_lbs"),
                "special_instructions": row.get("special_instructions"),
            }
        )
        out[bid] = fp
    return out


def write_fingerprint_seed(path: str, fingerprints: dict[str, str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"fingerprints": fingerprints}, f)


def read_fingerprint_seed(path: str) -> dict[str, str]:
    try:
        data = json.load(open(path, encoding="utf-8"))
        fps = data.get("fingerprints") if isinstance(data, dict) else None
        if isinstance(fps, dict):
            return {str(k).upper(): str(v) for k, v in fps.items()}
    except Exception:
        pass
    return {}
