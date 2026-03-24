#!/bin/bash
# Azure App Service (Linux): set Startup Command to:
#   bash startup.sh
# Or paste the gunicorn line below into Configuration → General settings → Startup Command.
set -e
cd "$(dirname "$0")"
export PYTHONUNBUFFERED=1
exec gunicorn --bind="0.0.0.0:${PORT:-8000}" --workers="${WORKERS:-2}" --timeout 600 backend.app:app
