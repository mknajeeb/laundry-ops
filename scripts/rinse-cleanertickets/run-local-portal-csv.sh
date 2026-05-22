#!/usr/bin/env bash
# Mac user scrape → portal CSV in tenants/<washpro|veewash>/TODAY/ (versioned, Eastern time).
# Double-click: run-local-portal-csv.command
#
# Usage:
#   bash run-local-portal-csv.sh
#   bash run-local-portal-csv.sh 3
#   RINSE_VENDOR=veewash bash run-local-portal-csv.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

TZ_NAME="America/New_York"

if [[ ! -f .env ]]; then
  echo "Missing .env in $ROOT — cp .env.example .env"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

VENDOR="$(bash "$ROOT/pick-rinse-vendor.sh")"
if [[ ! -f "$ROOT/tenants/$VENDOR/.env" ]]; then
  echo "Missing tenants/$VENDOR/.env — cp tenants/$VENDOR/.env.example tenants/$VENDOR/.env"
  echo "Run save-session.command for $VENDOR first."
  exit 1
fi
# shellcheck disable=SC1091
source "$ROOT/vendor-layout.sh" "$VENDOR"

echo ""
echo "=== Rinse export: $(printf '%s' "$VENDOR" | tr '[:lower:]' '[:upper:]') ==="
echo "Auth: $RINSE_STORAGE_STATE"
echo "Output folder: $TENANT_TODAY"
echo ""

if [[ ! -f "$RINSE_STORAGE_STATE" ]]; then
  echo "No saved session for $VENDOR."
  echo "Run save-session.command and log in with the $VENDOR Rinse account."
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
  echo "RINSE_MAX_PAGES=$RINSE_MAX_PAGES"
fi

TODAY_ET="$(TZ="$TZ_NAME" date +%F)"
STAMP_ET="$(TZ="$TZ_NAME" date +%Y%m%d_%H%M%S)"
ZONE_LABEL="$(TZ="$TZ_NAME" date +%Z)"

max_version=0
shopt -s nullglob
for f in "$TENANT_TODAY"/Rinse-"$TODAY_ET"-v*.csv "$TENANT_ARCHIVE"/Rinse-"$TODAY_ET"-v*.csv; do
  name="$(basename "$f")"
  if [[ "$name" =~ ^Rinse-$TODAY_ET-v([0-9]+)\.csv$ ]]; then
    ver="${BASH_REMATCH[1]}"
    (( ver > max_version )) && max_version=$ver
  elif [[ "$name" =~ ^Rinse-$TODAY_ET-v([0-9]+)_archived_ ]]; then
    ver="${BASH_REMATCH[1]}"
    (( ver > max_version )) && max_version=$ver
  fi
done
shopt -u nullglob

next_version=$((max_version + 1))
TMP_OUT="$TENANT_TODAY/_incoming_${STAMP_ET}_${ZONE_LABEL}.csv"
FINAL_NAME="Rinse-${TODAY_ET}-v${next_version}.csv"
FINAL_OUT="$TENANT_TODAY/$FINAL_NAME"

export OUTPUT_CSV="$TMP_OUT"

echo "Running scrape…"
npm run scrape

if [[ ! -f "$TMP_OUT" ]]; then
  echo "Scrape finished, but no CSV was created."
  exit 1
fi

shopt -s nullglob
for f in "$TENANT_TODAY"/*.csv; do
  [[ "$f" == "$TMP_OUT" ]] && continue
  base="$(basename "$f" .csv)"
  mv "$f" "$TENANT_ARCHIVE/${base}_archived_${STAMP_ET}_${ZONE_LABEL}.csv"
done
shopt -u nullglob

mv "$TMP_OUT" "$FINAL_OUT"

echo ""
echo "Done ($VENDOR)."
echo "New file:"
echo "  $FINAL_OUT"
echo "Older TODAY file(s) moved to:"
echo "  $TENANT_ARCHIVE"
echo "Timezone: $TZ_NAME ($ZONE_LABEL)"
