#!/usr/bin/env python3
"""
Local CLI for Rinse scan-events (split CSVs from scrape-scan-events.mjs).

Examples (repo root):
  python3 -m backend.rinse_scan_events_cli apply --csv scripts/rinse-cleanertickets/scan-events-2026-05-16-events.csv
  python3 -m backend.rinse_scan_events_cli portal-orders --csv scripts/rinse-cleanertickets/scan-events-2026-05-16-events.csv
  python3 -m backend.rinse_scan_events_cli portal-orders --tickets scripts/rinse-cleanertickets/scan-events-2026-05-16-tickets.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.rinse_scan_events_logic import (
    apply_scan_event_logic,
    load_scan_events_csv,
    portal_orders_from_tickets_csv,
    resolve_tickets_csv_path,
    summarize_scan_events,
)


def _cmd_apply(args: argparse.Namespace) -> int:
    df = load_scan_events_csv(args.csv)
    enriched = apply_scan_event_logic(df)
    out_path = args.out or str(Path(args.csv).with_name(Path(args.csv).stem + "-enriched.csv"))
    enriched.to_csv(out_path, index=False)
    print(f"Wrote {len(enriched)} event row(s) → {out_path}")
    if args.json_summary:
        print(json.dumps(summarize_scan_events(enriched), indent=2))
    return 0


def _cmd_summary(args: argparse.Namespace) -> int:
    df = load_scan_events_csv(args.csv)
    print(json.dumps(summarize_scan_events(df), indent=2))
    return 0


def _cmd_portal_orders(args: argparse.Namespace) -> int:
    if args.tickets:
        tickets = args.tickets
    elif args.csv:
        tickets = resolve_tickets_csv_path(args.csv)
    else:
        raise ValueError("Provide --tickets or --csv (events path to find sibling *-tickets.csv)")
    orders = portal_orders_from_tickets_csv(tickets)
    print(f"Portal orders rows: {len(orders)} (production portal_csv_to_orders_df)")
    print(f"Tickets file: {tickets}")
    if args.json_summary:
        print(json.dumps({"orders_rows": len(orders), "tickets_csv": tickets}, indent=2))
    if args.out:
        orders.to_csv(args.out, index=False)
        print(f"Wrote → {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rinse scan-events CSV tools (local)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_apply = sub.add_parser("apply", help="Apply event logic to *-events.csv")
    p_apply.add_argument("--csv", required=True, help="Path to *-events.csv")
    p_apply.add_argument("--out", help="Output CSV (default: <input>-enriched.csv)")
    p_apply.add_argument("--json-summary", action="store_true")
    p_apply.set_defaults(func=_cmd_apply)

    p_sum = sub.add_parser("summary", help="Summary JSON for *-events.csv")
    p_sum.add_argument("--csv", required=True)
    p_sum.set_defaults(func=_cmd_summary)

    p_portal = sub.add_parser("portal-orders", help="Production portal import from *-tickets.csv")
    p_portal.add_argument(
        "--csv",
        help="Path to *-events.csv (used to find sibling *-tickets.csv if --tickets omitted)",
    )
    p_portal.add_argument("--tickets", help="Path to *-tickets.csv (production portal layout)")
    p_portal.add_argument("--out", help="Optional orders CSV output")
    p_portal.add_argument("--json-summary", action="store_true")
    p_portal.set_defaults(func=_cmd_portal_orders)

    args = parser.parse_args(argv)
    if args.command == "portal-orders" and not args.tickets and not args.csv:
        parser.error("portal-orders requires --tickets or --csv (events path to locate tickets file)")
    try:
        return args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
