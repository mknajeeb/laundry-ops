#!/usr/bin/env bash
# Save Rinse login cookies for WashPro or VeeWash (run once per vendor, or when session expires).
# Mac: double-click save-session.command
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

VENDOR="$(bash "$ROOT/pick-rinse-vendor.sh")"
if [[ ! -f "$ROOT/tenants/$VENDOR/.env" && -f "$ROOT/tenants/$VENDOR/.env.example" ]]; then
  cp "$ROOT/tenants/$VENDOR/.env.example" "$ROOT/tenants/$VENDOR/.env"
  echo "Created tenants/$VENDOR/.env — edit RINSE_TICKETS_URL before scraping."
fi
# shellcheck disable=SC1091
source "$ROOT/vendor-layout.sh" "$VENDOR"

echo ""
echo "=== Save Rinse session: $(printf '%s' "$VENDOR" | tr '[:lower:]' '[:upper:]') ==="
echo "Will save to: $RINSE_STORAGE_STATE"
echo ""

if [[ ! -d node_modules ]]; then
  npm install
fi
npx playwright install chromium

HEADED=1 node save-session.mjs

echo ""
echo "Saved for $VENDOR. You can run run-local-portal-csv.command next."
