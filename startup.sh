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
echo "startup.sh: begin $(date -u +%Y-%m-%dT%H:%M:%SZ) cwd=$(pwd)"

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

# Keep deps on persistent /home so restarts do not re-download pandas/mysql/etc. every time
# (new instances still run pip once when requirements.txt changes).
_PY="python3"
command -v "$_PY" >/dev/null 2>&1 || _PY="python"
VENV="/home/site/laundry_venv"
REQ_HASH_FILE="/home/site/.laundry_requirements.sha256"
if [ -f requirements.txt ]; then
  _hash="$(sha256sum requirements.txt 2>/dev/null | awk '{print $1}' || true)"
  _reuse=0
  if [ -n "$_hash" ] && [ -x "$VENV/bin/gunicorn" ] && [ -f "$REQ_HASH_FILE" ] && [ "$(cat "$REQ_HASH_FILE")" = "$_hash" ]; then
    _reuse=1
  fi
  if [ "$_reuse" = "1" ]; then
    printf 'startup.sh: using persistent venv %s; requirements unchanged\n' "$VENV"
  else
    printf 'startup.sh: updating venv at %s; first boot or requirements changed\n' "$VENV"
    mkdir -p /home/site
    if [ ! -x "$VENV/bin/python" ]; then
      "$_PY" -m venv "$VENV" || { echo "startup.sh: FATAL could not create venv"; exit 1; }
    fi
    if ! "$VENV/bin/python" -m pip install --upgrade pip setuptools wheel; then
      echo "startup.sh: warning: pip upgrade in venv failed; continuing"
    fi
    if ! "$VENV/bin/python" -m pip install --no-cache-dir -r requirements.txt; then
      echo "startup.sh: FATAL pip install in venv failed - fix requirements or disk; delete $VENV to retry clean."
      exit 1
    fi
    if [ -n "$_hash" ]; then
      echo "$_hash" > "$REQ_HASH_FILE"
    fi
  fi
fi

# Rinse bag export: scrape.mjs needs node_modules (Playwright). Each Git deploy replaces wwwroot and
# deletes local node_modules — keep them under /home/site and symlink from the app folder.
#
# If startup hits Azure's container time limit or npm/playwright fails hard, set in App Service
# Configuration → Application settings:
#   LAUNDRYOPS_SKIP_RINSE_STARTUP=1
# The API will still run; Rinse CSV export will fail until Node/Playwright is fixed or this is cleared.
RINSE_DIR="scripts/rinse-cleanertickets"
RINSE_NM_PERSIST="/home/site/rinse_scraper_node_modules"
PW_MARK="/home/site/.rinse_playwright_chromium_ok"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/home/site/ms-playwright}"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"

if [ -z "${NODE_BIN:-}" ] && [ -x "/home/site/node-v20.18.0-linux-x64/bin/node" ]; then
  export NODE_BIN="/home/site/node-v20.18.0-linux-x64/bin/node"
fi

# Portal may store "True", " TRUE ", etc. — must normalize or the Rinse branch still runs (long apt).
_raw_skip="${LAUNDRYOPS_SKIP_RINSE_STARTUP:-}"
_SKIP_RINSE="$(printf '%s' "$_raw_skip" | tr '[:upper:]' '[:lower:]' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
echo "startup.sh: LAUNDRYOPS_SKIP_RINSE_STARTUP raw='${_raw_skip}' normalized='${_SKIP_RINSE}'"
if [ "$_SKIP_RINSE" = "1" ] || [ "$_SKIP_RINSE" = "true" ] || [ "$_SKIP_RINSE" = "yes" ] || [ "$_SKIP_RINSE" = "on" ]; then
  echo "startup.sh: skipping Rinse/Playwright bootstrap (LAUNDRYOPS_SKIP_RINSE_STARTUP)"
elif [ -f "$RINSE_DIR/package.json" ] && [ -n "${NODE_BIN:-}" ] && [ -x "$NODE_BIN" ]; then
  _nd="$(dirname "$NODE_BIN")"
  _prefix="$(dirname "$_nd")"
  NPM_CLI="$_prefix/lib/node_modules/npm/bin/npm-cli.js"
  mkdir -p "$RINSE_NM_PERSIST"
  rm -rf "$RINSE_DIR/node_modules"
  ln -sfn "$RINSE_NM_PERSIST" "$RINSE_DIR/node_modules"
  echo "startup.sh: npm install in ${RINSE_DIR} (persistent ${RINSE_NM_PERSIST})"
  # npm/playwright can exceed Azure's startup window; cap wait so gunicorn still starts (Rinse export may fail until deps finish).
  _npm_to="${RINSE_NPM_INSTALL_TIMEOUT_SEC:-480}"
  if [ -f "$NPM_CLI" ]; then
    if command -v timeout >/dev/null 2>&1 && [ "$_npm_to" -gt 0 ] 2>/dev/null; then
      echo "startup.sh: npm install max wait ${_npm_to}s (set RINSE_NPM_INSTALL_TIMEOUT_SEC=0 to disable cap)"
      (cd "$RINSE_DIR" && timeout "$_npm_to" "$NODE_BIN" "$NPM_CLI" install --omit=dev --no-audit --no-fund) \
        || echo "startup.sh: warning: npm install failed or timed out (${_npm_to}s); API will still start"
    else
      (cd "$RINSE_DIR" && "$NODE_BIN" "$NPM_CLI" install --omit=dev --no-audit --no-fund) \
        || echo "startup.sh: warning: npm install failed"
    fi
  elif [ -x "$_nd/npm" ]; then
    if command -v timeout >/dev/null 2>&1 && [ "$_npm_to" -gt 0 ] 2>/dev/null; then
      (cd "$RINSE_DIR" && timeout "$_npm_to" "$_nd/npm" install --omit=dev --no-audit --no-fund) \
        || echo "startup.sh: warning: npm install failed or timed out (${_npm_to}s); API will still start"
    else
      (cd "$RINSE_DIR" && "$_nd/npm" install --omit=dev --no-audit --no-fund) \
        || echo "startup.sh: warning: npm install failed"
    fi
  else
    echo "startup.sh: warning: npm-cli.js not found at $NPM_CLI"
  fi
  # Absolute path: inside (cd "$RINSE_DIR" && node "$PW_CLI" ...) a relative PW_CLI is resolved
  # against cwd and becomes scripts/rinse-cleanertickets/scripts/rinse-cleanertickets/... (wrong).
  PW_CLI="$(pwd)/$RINSE_DIR/node_modules/playwright/cli.js"
  if [ ! -f "$PW_MARK" ] && [ -f "$PW_CLI" ]; then
    _pw_to="${RINSE_PLAYWRIGHT_BROWSER_INSTALL_TIMEOUT_SEC:-600}"
    echo "startup.sh: Playwright chromium (first run; max wait ${_pw_to}s, 0=unlimited)"
    if command -v timeout >/dev/null 2>&1 && [ "$_pw_to" -gt 0 ] 2>/dev/null; then
      (cd "$RINSE_DIR" && timeout "$_pw_to" "$NODE_BIN" "$PW_CLI" install chromium && touch "$PW_MARK") \
        || echo "startup.sh: warning: playwright install chromium failed or timed out (${_pw_to}s)"
    else
      (cd "$RINSE_DIR" && "$NODE_BIN" "$PW_CLI" install chromium && touch "$PW_MARK") \
        || echo "startup.sh: warning: playwright install chromium failed"
    fi
  fi
  SYSDEPS_MARK="/home/site/.rinse_playwright_sysdeps_ok"
  # Marker lives on persistent /home; new workers may lack /usr packages — recheck libglib.
  GLIB_LIB="/usr/lib/x86_64-linux-gnu/libglib-2.0.so.0"
  if [ -f "$PW_CLI" ] && { [ ! -f "$SYSDEPS_MARK" ] || [ ! -f "$GLIB_LIB" ]; }; then
    _ideps_to="${RINSE_PLAYWRIGHT_INSTALL_DEPS_TIMEOUT_SEC:-900}"
    echo "startup.sh: Playwright system dependencies (apt), max wait ${_ideps_to}s"
    if command -v timeout >/dev/null 2>&1 && [ "${_ideps_to:-0}" -gt 0 ] 2>/dev/null; then
      if (cd "$RINSE_DIR" && timeout "$_ideps_to" "$NODE_BIN" "$PW_CLI" install-deps chromium); then
        touch "$SYSDEPS_MARK"
      else
        echo "startup.sh: warning: playwright install-deps failed or timed out (${_ideps_to}s) — API still starts; run install-deps over SSH if Chromium fails"
      fi
    elif (cd "$RINSE_DIR" && "$NODE_BIN" "$PW_CLI" install-deps chromium); then
      touch "$SYSDEPS_MARK"
    else
      echo "startup.sh: warning: playwright install-deps failed — run once as root over SSH (see backend rinse runner error text)"
    fi
  fi
else
  echo "startup.sh: Rinse scraper deps skipped (set NODE_BIN, e.g. /home/site/node-v20.18.0-linux-x64/bin/node)"
fi

echo "startup.sh: starting gunicorn on 0.0.0.0:${PORT:-8000} workers=${WORKERS:-2} timeout=${GUNICORN_TIMEOUT:-1200}"
# Rinse export can run Playwright for up to RINSE_SCRAPE_TIMEOUT_SEC (default 900s, max 7200s); worker must outlive that.
if [ -x "$VENV/bin/gunicorn" ]; then
  exec "$VENV/bin/gunicorn" --bind="0.0.0.0:${PORT:-8000}" --workers="${WORKERS:-2}" --timeout="${GUNICORN_TIMEOUT:-1200}" backend.app:app
fi
exec gunicorn --bind="0.0.0.0:${PORT:-8000}" --workers="${WORKERS:-2}" --timeout="${GUNICORN_TIMEOUT:-1200}" backend.app:app
