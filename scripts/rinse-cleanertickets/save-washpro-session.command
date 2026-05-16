#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "======================================"
echo "Saving WashPro Rinse login session"
echo "======================================"
echo ""

mkdir -p tenants/washpro/TODAY tenants/washpro/ARCHIVE

if [[ ! -d node_modules ]]; then
  echo "Installing npm dependencies (first time)…"
  npm install
fi
npx playwright install chromium

export RINSE_STORAGE_STATE="$PWD/tenants/washpro/rinse-auth.json"
export RINSE_TICKETS_URL="https://www.rinse.com/cleanertickets/?q=&status=at_vendor&page=1"

node save-session.mjs

echo ""
echo "WashPro session saved:"
echo "$RINSE_STORAGE_STATE"
echo ""
read -r -p "Press Enter to close… " _
