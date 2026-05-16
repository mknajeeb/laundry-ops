#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "======================================"
echo "WashPro Rinse scan-events export"
echo "======================================"
echo ""

if [[ ! -f "tenants/washpro/rinse-auth.json" ]]; then
  echo "ERROR: WashPro login session not found."
  echo "First double-click: save-washpro-session.command"
  echo ""
  read -r -p "Press Enter to close… " _
  exit 1
fi

mkdir -p tenants/washpro/TODAY tenants/washpro/ARCHIVE

if [[ ! -d node_modules ]]; then
  echo "Installing npm dependencies (first time)…"
  npm install
fi
echo "Ensuring Chromium is installed…"
npx playwright install chromium

DATESTAMP="$(date +"%Y-%m-%d-%H%M")"
OUTPUT_CSV="$PWD/tenants/washpro/TODAY/washpro-scan-events-${DATESTAMP}.csv"

export RINSE_TICKETS_URL="https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1"
export RINSE_SCAN_OUTPUT_LAYOUT=events_only
export RINSE_STORAGE_STATE="$PWD/tenants/washpro/rinse-auth.json"
export OUTPUT_SCAN_EVENTS_CSV="$OUTPUT_CSV"
export OUTPUT_CSV="$OUTPUT_CSV"

node scrape-scan-events.mjs

echo ""
echo "Done."
echo "Optional: upload this file in Laundry Ops → Upload Orders → Rinse Events CSV:"
echo "$OUTPUT_CSV"
echo "(Does not replace the regular portal order CSV.)"
echo ""
read -r -p "Press Enter to close… " _
