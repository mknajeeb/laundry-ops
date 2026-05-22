#!/usr/bin/env bash
# Set per-vendor paths. Usage: source vendor-layout.sh washpro
# Requires ROOT set to rinse-cleanertickets directory.
set -euo pipefail

VENDOR="${1:-}"
case "$VENDOR" in
  washpro|veewash) ;;
  *)
    echo "vendor-layout.sh: expected washpro or veewash, got: $VENDOR" >&2
    return 1 2>/dev/null || exit 1
    ;;
esac

if [[ -z "${ROOT:-}" ]]; then
  echo "vendor-layout.sh: ROOT not set" >&2
  return 1 2>/dev/null || exit 1
fi

export RINSE_VENDOR="$VENDOR"
export TENANT_DIR="$ROOT/tenants/$VENDOR"

# Per-vendor credentials (email, password, tickets URL) — separate from shared .env
if [[ -f "$TENANT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$TENANT_DIR/.env"
  set +a
fi

export RINSE_STORAGE_STATE="${RINSE_STORAGE_STATE:-$TENANT_DIR/rinse-auth.json}"
if [[ "$RINSE_STORAGE_STATE" != /* ]]; then
  export RINSE_STORAGE_STATE="$TENANT_DIR/${RINSE_STORAGE_STATE#./}"
fi
export TENANT_TODAY="$TENANT_DIR/TODAY"
export TENANT_ARCHIVE="$TENANT_DIR/ARCHIVE"

mkdir -p "$TENANT_TODAY" "$TENANT_ARCHIVE"

# Scan-events outputs (if used)
export OUTPUT_SCAN_TICKETS_CSV="${OUTPUT_SCAN_TICKETS_CSV:-$TENANT_DIR/scan-events-tickets.csv}"
export OUTPUT_SCAN_EVENTS_CSV="${OUTPUT_SCAN_EVENTS_CSV:-$TENANT_DIR/scan-events-events.csv}"
