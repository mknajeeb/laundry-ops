#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")/.." && pwd)/_tenant-env.sh" "${BASH_SOURCE[0]}"

if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
  export RINSE_MAX_PAGES="$1"
  echo "RINSE_MAX_PAGES=$RINSE_MAX_PAGES"
fi

STAMP="$(date +%Y-%m-%d)"
export OUTPUT_SCAN_TICKETS_CSV="${OUTPUT_SCAN_TICKETS_CSV:-$TENANT_DIR/output/scan-events-$STAMP-tickets.csv}"
export OUTPUT_SCAN_EVENTS_CSV="${OUTPUT_SCAN_EVENTS_CSV:-$TENANT_DIR/output/scan-events-$STAMP-events.csv}"

echo "VEEWASH scan-events →"
echo "  $OUTPUT_SCAN_TICKETS_CSV"
echo "  $OUTPUT_SCAN_EVENTS_CSV"
exec node scrape-scan-events.mjs
