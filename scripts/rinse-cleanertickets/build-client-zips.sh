#!/usr/bin/env bash
# Build Mac and Windows client zip packages (no secrets, no node_modules).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$ROOT/../.." && pwd)"
OUT="$REPO/dist-rinse-client"
STAGE="$OUT/staging"
rm -rf "$STAGE"
mkdir -p "$STAGE/mac/rinse-cleanertickets" "$STAGE/win/rinse-cleanertickets"

copy_common() {
  local dest="$1"
  cp \
    "$ROOT/scrape.mjs" \
    "$ROOT/scrape-scan-events.mjs" \
    "$ROOT/rinse-playwright-lib.mjs" \
    "$ROOT/save-session.mjs" \
    "$ROOT/package.json" \
    "$ROOT/package-lock.json" \
    "$ROOT/CLIENT_README.txt" \
    "$dest/"
  cp "$ROOT/.env.example" "$dest/"
  mkdir -p "$dest/tenants/washpro/TODAY" "$dest/tenants/washpro/ARCHIVE"
  mkdir -p "$dest/tenants/veewash/TODAY" "$dest/tenants/veewash/ARCHIVE"
  cp "$ROOT/tenants/washpro/.env.example" "$dest/tenants/washpro/"
  cp "$ROOT/tenants/veewash/.env.example" "$dest/tenants/veewash/"
  touch "$dest/tenants/washpro/TODAY/.keep" "$dest/tenants/washpro/ARCHIVE/.keep"
  touch "$dest/tenants/veewash/TODAY/.keep" "$dest/tenants/veewash/ARCHIVE/.keep"
}

copy_common "$STAGE/mac/rinse-cleanertickets"
cp \
  "$ROOT/save-washpro-session.command" \
  "$ROOT/save-veewash-session.command" \
  "$ROOT/run-washpro-portal-csv.command" \
  "$ROOT/run-veewash-portal-csv.command" \
  "$ROOT/run-washpro-scan-events.command" \
  "$ROOT/run-veewash-scan-events.command" \
  "$STAGE/mac/rinse-cleanertickets/"
chmod +x "$STAGE/mac/rinse-cleanertickets"/*.command

copy_common "$STAGE/win/rinse-cleanertickets"
cp "$ROOT"/*.cmd "$STAGE/win/rinse-cleanertickets/" 2>/dev/null || true
cp "$ROOT/pick-rinse-vendor.mjs" "$STAGE/win/rinse-cleanertickets/" 2>/dev/null || true

mkdir -p "$OUT"
( cd "$STAGE/mac" && zip -r "$OUT/rinse-cleanertickets-mac-client.zip" rinse-cleanertickets -x "*.DS_Store" -x "__MACOSX/*" )
( cd "$STAGE/win" && zip -r "$OUT/rinse-cleanertickets-windows-client.zip" rinse-cleanertickets -x "*.DS_Store" -x "__MACOSX/*" )

rm -rf "$OUT/windows/rinse-cleanertickets"
mkdir -p "$OUT/windows"
cp -R "$STAGE/win/rinse-cleanertickets" "$OUT/windows/rinse-cleanertickets"

rm -rf "$STAGE"
echo "Built:"
ls -lh "$OUT"/*.zip
