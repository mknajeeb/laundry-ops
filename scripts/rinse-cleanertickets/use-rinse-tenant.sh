#!/usr/bin/env bash
# Load per-tenant Rinse config then run a command (WASHPRO vs VEEWASH, etc.).
#
# Setup once per tenant:
#   cp .env.washpro.example .env.washpro
#   cp .env.veewash.example .env.veewash
#   ./use-rinse-tenant.sh washpro npm run save-session
#   ./use-rinse-tenant.sh veewash npm run save-session
#
# Scrape:
#   ./use-rinse-tenant.sh washpro bash run-local-production-scrape.sh 1
#   ./use-rinse-tenant.sh veewash bash run-local-scan-events.sh 1

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

TENANT="${1:-}"
shift || true

if [[ -z "$TENANT" ]]; then
  echo "Usage: $0 <tenant> <command...>"
  echo "  tenant: washpro | veewash (file: .env.<tenant>)"
  echo ""
  echo "Examples:"
  echo "  $0 washpro npm run save-session"
  echo "  $0 veewash bash run-local-production-scrape.sh 1"
  exit 1
fi

ENV_FILE="$ROOT/.env.$TENANT"
if [[ ! -f "$ENV_FILE" ]]; then
  EXAMPLE="$ROOT/.env.$TENANT.example"
  echo "Missing $ENV_FILE"
  [[ -f "$EXAMPLE" ]] && echo "  cp $EXAMPLE $ENV_FILE"
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

echo "[rinse tenant=$TENANT] RINSE_STORAGE_STATE=${RINSE_STORAGE_STATE:-<unset>}"
echo "[rinse tenant=$TENANT] RINSE_TICKETS_URL=${RINSE_TICKETS_URL:-<unset>}"

if [[ $# -eq 0 ]]; then
  echo "No command — env loaded. Run scrape commands in this shell:"
  echo "  source $ENV_FILE && set -a && source $ENV_FILE && set +a"
  exit 0
fi

exec "$@"
