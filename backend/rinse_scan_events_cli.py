#!/usr/bin/env python3
"""
Local CLI for Rinse scan-events CSV (from scripts/rinse-cleanertickets/scrape-scan-events.mjs).

Examples (repo root):
  python -m backend.rinse_scan_events_cli apply --csv scripts/rinse-cleanertickets/scan-events-2026-05-11.csv
  python -m backend.rinse_scan_events_cli apply --csv path/to.csv --out enriched.csv
  python -m backend.rinse_scan_events_cli summary --csv path/to.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.rinse_scan_events_logic import (
    apply_scan_event_logic,
    load_scan_events_csv,
    summarize_scan_events,
)


def _cmd_apply(args: argparse.Namespace) -> int:
    df = load_scan_events_csv(args.csv)
    enriched = apply_scan_event_logic(df)
    out_path = args.out or str(Path(args.csv).with_name(Path(args.csv).stem + "-enriched.csv"))
    enriched.to_csv(out_path, index=False)
    print(f"Wrote {len(enriched)} row(s) → {out_path}")
    if args.json_summary:
        print(json.dumps(summarize_scan_events(enriched), indent=2))
    return 0


def _cmd_summary(args: argparse.Namespace) -> int:
    df = load_scan_events_csv(args.csv)
    print(json.dumps(summarize_scan_events(df), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rinse scan-events CSV tools (local)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_apply = sub.add_parser("apply", help="Apply logic and write enriched CSV")
    p_apply.add_argument("--csv", required=True, help="Path to scan-events CSV from scrape-scan-events.mjs")
    p_apply.add_argument("--out", help="Output CSV path (default: <input>-enriched.csv)")
    p_apply.add_argument("--json-summary", action="store_true", help="Print summary JSON to stdout")
    p_apply.set_defaults(func=_cmd_apply)

    p_sum = sub.add_parser("summary", help="Print summary JSON only")
    p_sum.add_argument("--csv", required=True)
    p_sum.set_defaults(func=_cmd_summary)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
