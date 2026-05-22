#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")/.." && pwd)/_tenant-env.sh" "${BASH_SOURCE[0]}"

if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
  export RINSE_MAX_PAGES="$1"
  echo "RINSE_MAX_PAGES=$RINSE_MAX_PAGES"
fi

STAMP="$(date +%Y-%m-%d)"
export OUTPUT_CSV="${OUTPUT_CSV:-$TENANT_DIR/output/bag-ids-$STAMP.csv}"

echo "VEEWASH production scrape → $OUTPUT_CSV"
exec node scrape.mjs
