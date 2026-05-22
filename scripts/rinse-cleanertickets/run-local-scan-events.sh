#!/usr/bin/env bash
# Scan-events export (tickets + events CSVs) per vendor folder under tenants/.
# Mac: run-local-scan-events.command
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — cp .env.example .env"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

VENDOR="$(bash "$ROOT/pick-rinse-vendor.sh")"
# shellcheck disable=SC1091
source "$ROOT/vendor-layout.sh" "$VENDOR"

if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
  export RINSE_MAX_PAGES="$1"
  shift
  echo "RINSE_MAX_PAGES=$RINSE_MAX_PAGES"
fi

STAMP="$(date +%Y-%m-%d)"
export OUTPUT_SCAN_TICKETS_CSV="$TENANT_DIR/scan-events-$STAMP-tickets.csv"
export OUTPUT_SCAN_EVENTS_CSV="$TENANT_DIR/scan-events-$STAMP-events.csv"

echo ""
echo "=== Scan events: $(printf '%s' "$VENDOR" | tr '[:lower:]' '[:upper:]') ==="
echo "  $OUTPUT_SCAN_TICKETS_CSV"
echo "  $OUTPUT_SCAN_EVENTS_CSV"
echo ""

if [[ ! -f "$RINSE_STORAGE_STATE" ]]; then
  echo "No session for $VENDOR — run save-session.command first."
  exit 1
fi

if [[ ! -d node_modules ]]; then
  npm install
fi
npx playwright install chromium

node scrape-scan-events.mjs

if [[ "${1:-}" == "--apply" ]]; then
  REPO="$(cd "$ROOT/../.." && pwd)"
  echo "Applying event logic…"
  (cd "$REPO" && python3 -m backend.rinse_scan_events_cli apply --csv "$OUTPUT_SCAN_EVENTS_CSV" --json-summary)
fi
