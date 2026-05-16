#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "======================================"
echo "Running VeeWash Rinse portal CSV scrape"
echo "======================================"
echo ""

if [[ ! -f "tenants/veewash/rinse-auth.json" ]]; then
  echo "ERROR: VeeWash login session not found."
  echo "First double-click: save-veewash-session.command"
  echo ""
  read -r -p "Press Enter to close… " _
  exit 1
fi

mkdir -p tenants/veewash/TODAY tenants/veewash/ARCHIVE

if [[ ! -d node_modules ]]; then
  echo "Installing npm dependencies (first time)…"
  npm install
fi
echo "Ensuring Chromium is installed…"
npx playwright install chromium

DATESTAMP="$(date +"%Y-%m-%d-%H%M")"
OUTPUT_CSV="$PWD/tenants/veewash/TODAY/veewash-portal-${DATESTAMP}.csv"

export RINSE_TICKETS_URL="https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1"
export RINSE_CSV_LAYOUT=portal
export RINSE_STORAGE_STATE="$PWD/tenants/veewash/rinse-auth.json"
export OUTPUT_CSV

node scrape.mjs

echo ""
echo "Done."
echo "Upload this file in Laundry Ops (Rinse / CSV):"
echo "$OUTPUT_CSV"
echo ""
read -r -p "Press Enter to close… " _
