#!/usr/bin/env bash
# Sourced by tenant run scripts — do not execute directly.
set -euo pipefail
TENANT_DIR="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
# scripts/rinse-tenants/<vendor> → scripts/rinse-cleanertickets (not tenants/rinse-cleanertickets)
SCRAPER_ROOT="$(cd "$TENANT_DIR/../../rinse-cleanertickets" && pwd)"

# Azure ACA / server: auth + .env live on the mounted volume (see RINSE_SCRAPE_DATA_ROOT).
if [[ -n "${RINSE_TENANT_DATA_DIR:-}" && -d "${RINSE_TENANT_DATA_DIR}" ]]; then
  TENANT_DIR="${RINSE_TENANT_DATA_DIR}"
fi

if [[ ! -f "$TENANT_DIR/.env" ]]; then
  echo "Missing $TENANT_DIR/.env — run: bash setup-all.sh"
  exit 1
fi

# Load tenant .env WITHOUT clobbering vars already set by the scheduled scrape
# supervisor (source URLs, full-traverse, lean settle timings). Prior `set -a;
# source .env` overwrote production timing and reintroduced slow waits.
_load_tenant_env_noforce() {
  local f="$1"
  local line key val
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "${line//[[:space:]]/}" ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ -z "$key" || "$key" == *[!A-Za-z0-9_]* ]] && continue
    # Strip optional surrounding quotes
    if [[ "$val" =~ ^\".*\"$ ]]; then
      val="${val:1:${#val}-2}"
    elif [[ "$val" =~ ^\'.*\'$ ]]; then
      val="${val:1:${#val}-2}"
    fi
    if [[ -z "${!key+x}" ]]; then
      export "${key}=${val}"
    fi
  done <"$f"
}
_load_tenant_env_noforce "$TENANT_DIR/.env"

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
