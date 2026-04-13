#!/bin/bash
# Azure App Service (Linux): set Startup Command to:
#   bash startup.sh
# Or paste the gunicorn line below into Configuration → General settings → Startup Command.
#
# When SCM_DO_BUILD_DURING_DEPLOYMENT=false, Oryx does not pip install on deploy. This repo's
# CI artifact excludes antenv/, so install deps here on container start (idempotent, ~tens of s).
#
# If deploy only dropped output.tar.zst (no loose files), unpack so backend/, scripts/, etc. exist.
set -e
cd "$(dirname "$0")"
export PYTHONUNBUFFERED=1

SCRAPE="scripts/rinse-cleanertickets/scrape.mjs"
if [ ! -f "$SCRAPE" ] && [ -f output.tar.zst ] && command -v zstd >/dev/null 2>&1; then
  echo "startup.sh: extracting output.tar.zst (missing ${SCRAPE})"
  zstd -dc output.tar.zst | tar xf -
fi

# Oryx tarball often includes antenv/ built for another layer; numpy then fails with missing
# libscipy_openblas64_*.so. Drop it and use this container's Python + pip only.
if [ -d antenv ]; then
  echo "startup.sh: removing bundled antenv (incompatible with this host)"
  rm -rf antenv
fi
unset VIRTUAL_ENV 2>/dev/null || true

if [ -f requirements.txt ]; then
  python -m pip install --no-cache-dir -r requirements.txt
fi

# Rinse bag export: scrape.mjs needs node_modules (Playwright). App Service Python images often have no npm.
# Set NODE_BIN to your node executable; its directory is prepended to PATH so npm/npx resolve.
if [ -n "${NODE_BIN:-}" ] && [ -x "$NODE_BIN" ]; then
  _node_dir="$(dirname "$NODE_BIN")"
  if [ "$_node_dir" != "." ]; then
    export PATH="$_node_dir:$PATH"
  fi
fi

RINSE_DIR="scripts/rinse-cleanertickets"
if [ -f "$RINSE_DIR/package.json" ] && command -v npm >/dev/null 2>&1; then
  echo "startup.sh: npm install in ${RINSE_DIR}"
  (cd "$RINSE_DIR" && npm install --omit=dev --no-audit --no-fund) || echo "startup.sh: warning: npm install failed"
  # Persist marker under /home/site so restarts skip the browser download when possible.
  if [ ! -f /home/site/.rinse_playwright_chromium_ok ]; then
    echo "startup.sh: Playwright chromium (first run; may take a few minutes)"
    (cd "$RINSE_DIR" && npx playwright install chromium && touch /home/site/.rinse_playwright_chromium_ok) \
      || echo "startup.sh: warning: playwright install chromium failed"
  fi
else
  echo "startup.sh: npm not found — Rinse scraper deps skipped (install Node or add to PATH; set NODE_BIN)"
fi

exec gunicorn --bind="0.0.0.0:${PORT:-8000}" --workers="${WORKERS:-2}" --timeout 600 backend.app:app
