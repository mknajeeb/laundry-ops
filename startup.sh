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

# Rinse bag export: scrape.mjs needs node_modules (Playwright). Each Git deploy replaces wwwroot and
# deletes local node_modules — keep them under /home/site and symlink from the app folder.
RINSE_DIR="scripts/rinse-cleanertickets"
RINSE_NM_PERSIST="/home/site/rinse_scraper_node_modules"
PW_MARK="/home/site/.rinse_playwright_chromium_ok"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/home/site/ms-playwright}"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"

if [ -z "${NODE_BIN:-}" ] && [ -x "/home/site/node-v20.18.0-linux-x64/bin/node" ]; then
  export NODE_BIN="/home/site/node-v20.18.0-linux-x64/bin/node"
fi

if [ -f "$RINSE_DIR/package.json" ] && [ -n "${NODE_BIN:-}" ] && [ -x "$NODE_BIN" ]; then
  _nd="$(dirname "$NODE_BIN")"
  _prefix="$(dirname "$_nd")"
  NPM_CLI="$_prefix/lib/node_modules/npm/bin/npm-cli.js"
  mkdir -p "$RINSE_NM_PERSIST"
  rm -rf "$RINSE_DIR/node_modules"
  ln -sfn "$RINSE_NM_PERSIST" "$RINSE_DIR/node_modules"
  echo "startup.sh: npm install in ${RINSE_DIR} (persistent ${RINSE_NM_PERSIST})"
  if [ -f "$NPM_CLI" ]; then
    (cd "$RINSE_DIR" && "$NODE_BIN" "$NPM_CLI" install --omit=dev --no-audit --no-fund) || echo "startup.sh: warning: npm install failed"
  elif [ -x "$_nd/npm" ]; then
    (cd "$RINSE_DIR" && "$_nd/npm" install --omit=dev --no-audit --no-fund) || echo "startup.sh: warning: npm install failed"
  else
    echo "startup.sh: warning: npm-cli.js not found at $NPM_CLI"
  fi
  PW_CLI="$RINSE_DIR/node_modules/playwright/cli.js"
  if [ ! -f "$PW_MARK" ] && [ -f "$PW_CLI" ]; then
    echo "startup.sh: Playwright chromium (first run; may take a few minutes)"
    (cd "$RINSE_DIR" && "$NODE_BIN" "$PW_CLI" install chromium && touch "$PW_MARK") \
      || echo "startup.sh: warning: playwright install chromium failed"
  fi
else
  echo "startup.sh: Rinse scraper deps skipped (set NODE_BIN, e.g. /home/site/node-v20.18.0-linux-x64/bin/node)"
fi

exec gunicorn --bind="0.0.0.0:${PORT:-8000}" --workers="${WORKERS:-2}" --timeout 600 backend.app:app
