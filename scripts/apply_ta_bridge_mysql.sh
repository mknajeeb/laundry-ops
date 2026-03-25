#!/usr/bin/env bash
# Apply backend/sql/ta_washpro_bridge.sql to Azure MySQL (creates ta_users + permission seeds).
# Loads MYSQL_* from project root .env if present.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQL_FILE="$ROOT/backend/sql/ta_washpro_bridge.sql"

if [[ ! -f "$SQL_FILE" ]]; then
  echo "Missing: $SQL_FILE"
  exit 1
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.env"
  set +a
fi

: "${MYSQL_HOST:?Set MYSQL_HOST (e.g. in .env)}"
: "${MYSQL_USER:?Set MYSQL_USER}"
: "${MYSQL_PASSWORD:?Set MYSQL_PASSWORD}"
: "${MYSQL_DATABASE:?Set MYSQL_DATABASE (e.g. laundryapp)}"
MYSQL_PORT="${MYSQL_PORT:-3306}"

echo "Applying $SQL_FILE → ${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE}"
echo "(You can also paste the same file into MySQL Workbench and run it there.)"

# Azure MySQL usually requires TLS; mysql client 8+ uses --ssl-mode=REQUIRED
EXTRA=()
if [[ "${MYSQL_SSL_REQUIRED:-}" == "1" ]] || [[ "${MYSQL_SSL_REQUIRED:-}" == "true" ]]; then
  EXTRA+=(--ssl-mode=REQUIRED)
fi
if [[ -n "${MYSQL_SSL_CA:-}" ]]; then
  EXTRA+=(--ssl-ca="$MYSQL_SSL_CA")
fi

mysql "${EXTRA[@]}" \
  -h "$MYSQL_HOST" -P "$MYSQL_PORT" \
  -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" \
  "$MYSQL_DATABASE" < "$SQL_FILE"

echo "Done. If other TA tables are missing (geofences, shift_sessions, …), plan a full TA schema with your DBA—see backend/schema_ta.sql (do not run DROP statements on production blindly)."
