#!/usr/bin/env bash
# Export Rinse "Scans" table per ticket → CSV → optional Python logic (local only).
# Does NOT run production scrape.mjs. See README_SCAN_EVENTS.md
#
# Usage:
#   bash run-local-scan-events.sh
#   bash run-local-scan-events.sh 3          # cap list pages
#   bash run-local-scan-events.sh 3 --apply  # scrape then enrich CSV

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — cp .env.example .env && npm run save-session"
  exit 1
fi

if [[ ! -d node_modules ]]; then
  echo "Installing npm dependencies…"
  npm install
fi
npx playwright install chromium

if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
  export RINSE_MAX_PAGES="$1"
  shift
  echo "RINSE_MAX_PAGES=$RINSE_MAX_PAGES"
fi

echo "Running scan-events scrape…"
node scrape-scan-events.mjs

CSV="${OUTPUT_SCAN_EVENTS_CSV:-}"
if [[ -z "$CSV" ]]; then
  CSV="$(ls -t scan-events-*.csv 2>/dev/null | head -1 || true)"
fi
if [[ -z "$CSV" || ! -f "$CSV" ]]; then
  echo "No scan-events CSV found. Set OUTPUT_SCAN_EVENTS_CSV in .env or check scrape output."
  exit 1
fi
CSV_ABS="$(cd "$(dirname "$CSV")" && pwd)/$(basename "$CSV")"
echo "CSV: $CSV_ABS"

if [[ "${1:-}" == "--apply" ]]; then
  REPO="$(cd "$ROOT/../.." && pwd)"
  echo "Applying logic → enriched CSV…"
  (cd "$REPO" && python3 -m backend.rinse_scan_events_cli apply --csv "$CSV_ABS" --json-summary)
fi
