#!/usr/bin/env bash
# Run Playwright on YOUR machine → portal CSV → upload in Washpro (Rinse / CSV).
# Full instructions for Mac/Windows users: USER_LOCAL_SCRAPE.md in this folder.
#
# One-time: cd here, npm install, npx playwright install chromium, cp .env.example .env,
#           edit .env, npm run save-session → rinse-auth.json
#
# Usage:
#   bash run-local-portal-csv.sh           # uses RINSE_MAX_PAGES from .env
#   bash run-local-portal-csv.sh 3         # cap at 3 list pages (quick test)

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env in $ROOT"
  echo "  cp .env.example .env"
  echo "  Edit RINSE_TICKETS_URL and RINSE_STORAGE_STATE=./rinse-auth.json"
  echo "  npm run save-session   # once, to create rinse-auth.json"
  exit 1
fi

if [[ ! -d node_modules ]]; then
  echo "Installing npm dependencies…"
  npm install
fi
echo "Ensuring Chromium is installed…"
npx playwright install chromium

export RINSE_CSV_LAYOUT=portal
if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
  export RINSE_MAX_PAGES="$1"
  echo "RINSE_MAX_PAGES=$RINSE_MAX_PAGES (quick test cap)"
fi

echo "Running scrape (portal CSV for upload)…"
npm run scrape
echo ""
echo "Next: Upload Orders → Rinse portal → draft → upload that CSV, or use Run portal scrape & load draft batch (API server)."
