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

if [ -f requirements.txt ]; then
  python -m pip install --no-cache-dir -r requirements.txt
fi

exec gunicorn --bind="0.0.0.0:${PORT:-8000}" --workers="${WORKERS:-2}" --timeout 600 backend.app:app
