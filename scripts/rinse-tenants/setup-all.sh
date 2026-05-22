#!/usr/bin/env bash
# Create washpro + veewash tenant dirs from examples.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

for t in washpro veewash; do
  mkdir -p "$t/output"
  touch "$t/output/.gitkeep"
  if [[ ! -f "$t/.env" ]]; then
    cp "$t/.env.example" "$t/.env"
    echo "Created $t/.env from example"
  else
    echo "Keep existing $t/.env"
  fi
  chmod +x "$t"/*.sh 2>/dev/null || true
done

SCRAPER="../rinse-cleanertickets"
if [[ ! -f "$SCRAPER/scrape.mjs" ]]; then
  echo "Warning: missing $SCRAPER/scrape.mjs"
else
  if [[ ! -d "$SCRAPER/node_modules" ]]; then
    echo "Installing npm deps in rinse-cleanertickets…"
    (cd "$SCRAPER" && npm install && npx playwright install chromium)
  fi
fi

echo ""
echo "Next:"
echo "  cd washpro && bash save-session.sh"
echo "  cd ../veewash && bash save-session.sh"
