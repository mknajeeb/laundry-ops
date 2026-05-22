#!/usr/bin/env bash
# Run production scrape.mjs (portal CSV only) for comparison with scan-events *-tickets.csv
#
# Usage:
#   bash run-local-production-scrape.sh
#   bash run-local-production-scrape.sh 3    # first 3 list pages only

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
  echo "RINSE_MAX_PAGES=$RINSE_MAX_PAGES"
fi

STAMP="$(date +%Y-%m-%d)"
export RINSE_CSV_LAYOUT=portal
export OUTPUT_CSV="${OUTPUT_CSV:-$ROOT/bag-ids-production-compare-$STAMP.csv}"

echo "Production scrape → $OUTPUT_CSV"
node scrape.mjs

echo ""
echo "Compare to scan-events tickets file from the same run, e.g.:"
echo "  diff -u \"$OUTPUT_CSV\" \"$ROOT/scan-events-${STAMP}-tickets.csv\""
echo "Or:  diff -u <(sort \"$OUTPUT_CSV\") <(sort \"$ROOT/scan-events-${STAMP}-tickets.csv\")"
