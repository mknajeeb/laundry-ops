#!/usr/bin/env bash
# Sourced by tenant run scripts — do not execute directly.
set -euo pipefail
TENANT_DIR="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
SCRAPER_ROOT="$(cd "$TENANT_DIR/../rinse-cleanertickets" && pwd)"

if [[ ! -f "$TENANT_DIR/.env" ]]; then
  echo "Missing $TENANT_DIR/.env — run: bash setup-all.sh"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$TENANT_DIR/.env"
set +a

mkdir -p "$TENANT_DIR/output"

export RINSE_CSV_LAYOUT="${RINSE_CSV_LAYOUT:-portal}"
export RINSE_STORAGE_STATE="${RINSE_STORAGE_STATE:-$TENANT_DIR/rinse-auth.json}"
# Resolve relative auth path from tenant dir
if [[ "$RINSE_STORAGE_STATE" != /* ]]; then
  export RINSE_STORAGE_STATE="$TENANT_DIR/$RINSE_STORAGE_STATE"
fi

if [[ ! -d "$SCRAPER_ROOT/node_modules" ]]; then
  echo "Installing scraper deps in $SCRAPER_ROOT…"
  (cd "$SCRAPER_ROOT" && npm install && npx playwright install chromium)
fi

cd "$SCRAPER_ROOT"
